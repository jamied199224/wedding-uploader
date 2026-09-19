import io
import json
import socket
import ssl
import time
import zipfile
import requests

import google_auth_httplib2
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httplib2
import streamlit as st

# Global socket timeout
socket.setdefaulttimeout(120)

st.set_page_config(
    page_title="Jamie & Millie's Wedding Album",
    page_icon="💍",
    layout="wide"
)

# --- HIGH-END GOOGLE PHOTOS GRID STYLING ---
st.markdown("""
<style>
    /* Seamless, tight photo grid layout */
    [data-testid="column"] {
        padding: 4px !important;
    }
    /* Modern square thumbnails with smooth rounded corners and shadow */
    .stImage img {
        border-radius: 12px !important;
        object-fit: cover !important;
        aspect-ratio: 1 / 1 !important;
        width: 100% !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
        transition: transform 0.2s ease;
    }
    .stImage img:hover {
        transform: scale(1.02);
    }
    /* Sleek, minimalist pill-shaped action buttons */
    .stButton button {
        width: 100%;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 500;
        padding: 4px 8px;
        background-color: #f8f9fa;
        color: #3c4043;
        border: 1px solid #dadce0;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .stButton button:hover {
        background-color: #f1f3f4;
        color: #1a73e8;
        border-color: #1a73e8;
    }
    /* Compact spacing */
    div.row-widget.stButton {
        margin-top: -2px;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

# Initialize session states
if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0
if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []
if 'my_likes' not in st.session_state:
    st.session_state.my_likes = set()

def get_credentials():
    """Retrieve and refresh Google OAuth credentials."""
    creds = Credentials(
        token=None,
        refresh_token=st.secrets["refresh_token"],
        client_id=st.secrets["client_id"],
        client_secret=st.secrets["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return creds

def create_drive_service():
    """Create a fresh Google Drive service."""
    creds = get_credentials()
    http = httplib2.Http(timeout=120)
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build('drive', 'v3', http=authorized_http)

def create_sheets_service():
    """Create a fresh Google Sheets service."""
    creds = get_credentials()
    http = httplib2.Http(timeout=120)
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build('sheets', 'v4', http=authorized_http)

@st.cache_resource
def get_google_services():
    try:
        drive = create_drive_service()
        sheets = create_sheets_service()
        return drive, sheets
    except Exception as e:
        st.error(f"Failed to authenticate with Google: {e}")
        return None, None

def get_or_create_likes_spreadsheet(drive_service, sheets_service, folder_id):
    """Find or create the Google Sheet used to store like counts with network retries."""
    query = f"'{folder_id}' in parents and name='wedding_likes_db' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    
    for attempt in range(3):
        try:
            res = drive_service.files().list(q=query, fields="files(id)").execute()
            files = res.get('files', [])
            
            if files:
                return files[0]['id']
                
            spreadsheet_body = {
                'properties': {'title': 'wedding_likes_db'}
            }
            sheet = sheets_service.spreadsheets().create(body=spreadsheet_body, fields='spreadsheetId').execute()
            sheet_id = sheet.get('spreadsheetId')
            
            file_obj = drive_service.files().get(fileId=sheet_id, fields='parents').execute()
            previous_parents = ",".join(file_obj.get('parents', []))
            drive_service.files().update(
                fileId=sheet_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            
            return sheet_id
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(2)
    return None

def load_likes_from_sheet(sheets_service, spreadsheet_id):
    """Load all file IDs and their like counts from the Google Sheet."""
    for attempt in range(3):
        try:
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range="A:B"
            ).execute()
            rows = result.get('values', [])
            likes_dict = {}
            for row in rows:
                if len(row) >= 1:
                    fid = row[0]
                    count_str = row[1] if len(row) > 1 else "0"
                    try:
                        likes_dict[fid] = int(count_str)
                    except ValueError:
                        likes_dict[fid] = 0
            return likes_dict
        except Exception as e:
            if attempt == 2:
                return {}
            time.sleep(1.5)
    return {}

def update_like_in_sheet(sheets_service, spreadsheet_id, file_id, delta):
    """Atomically update a specific file's like count in the Google Sheet."""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="A:B"
        ).execute()
        rows = result.get('values', [])
        
        found = False
        new_count = 0
        updated_rows = []
        
        for row in rows:
            if len(row) >= 1 and row[0] == file_id:
                found = True
                try:
                    cur = int(row[1]) if len(row) > 1 else 0
                except ValueError:
                    cur = 0
                new_count = max(0, cur + delta)
                updated_rows.append([file_id, str(new_count)])
            else:
                if len(row) > 0:
                    updated_rows.append(row)
                
        if not found:
            new_count = max(0, delta)
            updated_rows.append([file_id, str(new_count)])
            
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range="A:Z"
        ).execute()
        
        if updated_rows:
            body = {'values': updated_rows}
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range="A1",
                valueInputOption="RAW",
                body=body
            ).execute()
        return new_count
    except Exception as e:
        return None

def remove_file_from_sheet(sheets_service, spreadsheet_id, file_id):
    """Remove a file's record from the Google Sheet when deleted."""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="A:B"
        ).execute()
        rows = result.get('values', [])
        new_rows = [r for r in rows if len(r) > 0 and r[0] != file_id]
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range="A:Z"
        ).execute()
        if new_rows:
            body = {'values': new_rows}
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range="A1",
                valueInputOption="RAW",
                body=body
            ).execute()
    except Exception as e:
        pass

def upload_file_to_drive(file_bytes, file_name, mime_type, folder_id):
    """Upload files reliably using resumable requests."""
    creds = get_credentials()
    headers = {"Authorization": f"Bearer {creds.token}"}
    
    init_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
    init_headers = {
        **headers,
        "X-Upload-Content-Type": mime_type,
        "X-Upload-Content-Length": str(len(file_bytes)),
        "Content-Type": "application/json; charset=UTF-8"
    }
    metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    
    init_res = requests.post(init_url, headers=init_headers, json=metadata, timeout=60)
    if init_res.status_code != 200:
        raise Exception(f"Failed to start upload session: {init_res.text}")
        
    upload_url = init_res.headers.get('Location')
    if not upload_url:
        raise Exception("Upload session missing Location header from Google Drive.")
        
    put_headers = {
        "Content-Type": mime_type,
        "Content-Length": str(len(file_bytes))
    }
    upload_res = requests.put(upload_url, headers=put_headers, data=file_bytes, timeout=300)
    
    if upload_res.status_code in [200, 201]:
        return upload_res.json().get('id')
    else:
        raise Exception(f"Upload failed ({upload_res.status_code}): {upload_res.text}")

# Initialize Google Services
drive_service, sheets_service = get_google_services()
spreadsheet_id = get_or_create_likes_spreadsheet(drive_service, sheets_service, TARGET_FOLDER_ID) if (drive_service and sheets_service) else None

if drive_service and sheets_service and not spreadsheet_id:
    st.warning("⚠️ Warning: Could not locate or create 'wedding_likes_db' Google Sheet in the target folder. Likes may not persist.")

st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite memories and browse the live gallery below.")
st.caption("✨ Select photos for ZIP download | Tap heart to like | Click View to expand")

tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Gallery"])

with tab1:
    st.header("Upload Photos & Videos")
    st.write("Choose files from your phone library or camera:")
    
    if "upload_msg" in st.session_state:
        st.success(st.session_state.upload_msg)
        del st.session_state.upload_msg

    uploaded_files = st.file_uploader(
        "Choose files from gallery", 
        type=["jpg", "jpeg", "png", "heic", "mp4", "mov"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}"
    )
    guest_name = st.text_input("Your Name / Family (Optional)")

    if uploaded_files:
        if st.button("Submit to Wedding Album", type="primary"):
            if not drive_service:
                st.error("Google services are not initialized. Check your secrets.")
            else:
                total_files = len(uploaded_files)
                progress_bar = st.progress(0)
                status_text = st.empty()
                success_count = 0
                failed_files = []
                
                clean_guest_name = guest_name.strip() if guest_name and guest_name.strip() else "Guest"
                
                for index, uploaded_file in enumerate(uploaded_files):
                    file_raw = uploaded_file.getvalue()
                    file_size_mb = len(file_raw) / (1024 * 1024)
                    
                    status_text.text(f"Uploading {index + 1} of {total_files}: {uploaded_file.name} ({file_size_mb:.1f} MB)...")
                    uploaded_successfully = False
                    last_err = None
                    
                    file_title = f"{clean_guest_name}_{uploaded_file.name}"
                    mime_type = uploaded_file.type or 'application/octet-stream'

                    for attempt in range(3):
                        try:
                            file_id = upload_file_to_drive(
                                file_raw, 
                                file_title, 
                                mime_type, 
                                TARGET_FOLDER_ID
                            )
                            if file_id:
                                if file_id not in st.session_state.my_uploads:
                                    st.session_state.my_uploads.append(file_id)
                                if spreadsheet_id and sheets_service:
                                    update_like_in_sheet(sheets_service, spreadsheet_id, file_id, 0)
                            uploaded_successfully = True
                            success_count += 1
                            break
                        except Exception as e:
                            last_err = e
                            time.sleep(1.5 * (attempt + 1))
                    
                    if not uploaded_successfully:
                        failed_files.append((uploaded_file.name, str(last_err)))
                    progress_bar.progress((index + 1) / total_files)
                
                status_text.empty()
                progress_bar.empty()
                
                if failed_files:
                    st.error(f"Failed to upload {len(failed_files)} file(s):")
                    for fname, err in failed_files:
                        st.write(f"- **{fname}**: {err}")
                
                if success_count > 0:
                    st.session_state.upload_msg = f"Successfully uploaded {success_count} of {total_files} memories!"
                    st.session_state.uploader_key += 1
                    st.rerun()

with tab2:
    st.header("Wedding Gallery")

    if drive_service and sheets_service:
        try:
            query = f"'{TARGET_FOLDER_ID}' in parents and name != 'wedding_likes_db' and trashed=false"
            results = drive_service.files().list(
                q=query,
                pageSize=100,
                fields="files(id, name, webViewLink, webContentLink, thumbnailLink, mimeType)",
                orderBy="createdTime desc"
            ).execute()
            
            files = results.get('files', [])
            likes_dict = load_likes_from_sheet(sheets_service, spreadsheet_id) if spreadsheet_id else {}

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                selected_for_zip = []

                # Render seamless 3-column photo grid
                cols_per_row = 3
                rows = [files[i:i + cols_per_row] for i in range(0, len(files), cols_per_row)]

                for row_files in rows:
                    col_slots = st.columns(cols_per_row)
                    for idx, file in enumerate(row_files):
                        fid = file.get('id')
                        raw_title = file.get('name', '')
                        mime = file.get('mimeType', '')
                        thumb_small = file.get('thumbnailLink', '').replace('=s220', '=s400')
                        full_image = file.get('thumbnailLink', '').replace('=s220', '=s1600')
                        preview_url = f"https://drive.google.com/file/d/{fid}/preview"
                        is_video = 'video' in mime or 'mp4' in mime or 'mov' in mime
                        
                        likes_count = int(likes_dict.get(fid, 0))
                        is_mine = fid in st.session_state.my_uploads
                        
                        if '_' in raw_title:
                            uploader_name = raw_title.split('_', 1)[0].strip()
                        else:
                            uploader_name = 'Guest'
                        if not uploader_name:
                            uploader_name = 'Guest'

                        with col_slots[idx]:
                            # Selection checkbox for ZIP download
                            is_selected = st.checkbox("Select", key=f"chk_{fid}", label_visibility="collapsed")
                            if is_selected:
                                selected_for_zip.append(fid)

                            # Media Thumbnail
                            if not is_video and thumb_small:
                                st.image(thumb_small, use_container_width=True)
                            else:
                                st.markdown("🎥 **Video File**")
                                st.markdown(f"[Watch Preview]({preview_url})", unsafe_allow_html=True)

                            st.caption(f"Added by **{uploader_name}**")

                            # Clean action buttons toolbar
                            b_col1, b_col2, b_col3 = st.columns([1.2, 1, 1])
                            
                            # Like Button
                            with b_col1:
                                heart_label = f"❤️ {likes_count}"
                                if st.button(heart_label, key=f"like_{fid}"):
                                    if fid in st.session_state.my_likes:
                                        st.session_state.my_likes.remove(fid)
                                        update_like_in_sheet(sheets_service, spreadsheet_id, file_id=fid, delta=-1)
                                    else:
                                        st.session_state.my_likes.add(fid)
                                        update_like_in_sheet(sheets_service, spreadsheet_id, file_id=fid, delta=1)
                                    st.rerun()

                            # Full View Modal Button
                            with b_col2:
                                if not is_video:
                                    if st.button("🔍 View", key=f"view_{fid}"):
                                        @st.dialog("Memory Preview")
                                        def show_modal():
                                            st.image(full_image, use_container_width=True)
                                            st.caption(f"Added by {uploader_name}")
                                        show_modal()

                            # Delete Button (for user's uploads)
                            with b_col3:
                                if is_mine:
                                    if st.button("🗑️", key=f"del_{fid}"):
                                        try:
                                            drive_service.files().delete(fileId=fid).execute()
                                            if spreadsheet_id and sheets_service:
                                                remove_file_from_sheet(sheets_service, spreadsheet_id, fid)
                                            if fid in st.session_state.my_uploads:
                                                st.session_state.my_uploads.remove(fid)
                                            st.success("Deleted!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Delete failed: {e}")

                            st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

                # --- BATCH ZIP DOWNLOAD BAR ---
                st.markdown("---")
                st.subheader("📦 Download Selected Memories")
                if selected_for_zip:
                    st.write(f"**{len(selected_for_zip)} item(s) selected.**")
                    if st.button("Generate & Download ZIP", type="primary"):
                        with st.spinner("Packaging memories into ZIP..."):
                            try:
                                zip_buffer = io.BytesIO()
                                creds = get_credentials()
                                headers = {"Authorization": f"Bearer {creds.token}"}

                                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                                    for fid in selected_for_zip:
                                        f_meta = drive_service.files().get(fileId=fid, fields="name").execute()
                                        file_name = f_meta.get("name", f"wedding_memory_{fid}.jpg")
                                        download_url = f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media"
                                        res = requests.get(download_url, headers=headers, timeout=120)
                                        if res.status_code == 200:
                                            zf.writestr(file_name, res.content)

                                zip_buffer.seek(0)
                                st.download_button(
                                    label="💾 Click here to save ZIP file",
                                    data=zip_buffer,
                                    file_name="wedding_memories.zip",
                                    mime="application/zip"
                                )
                            except Exception as e:
                                st.error(f"Error creating ZIP: {e}")
                else:
                    st.info("Check the small selection box on any photo above to select it for ZIP download.")

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

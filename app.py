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

TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0

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

drive_service, sheets_service = get_google_services()
spreadsheet_id = get_or_create_likes_spreadsheet(drive_service, sheets_service, TARGET_FOLDER_ID) if (drive_service and sheets_service) else None

if drive_service and sheets_service and not spreadsheet_id:
    st.warning("⚠️ Warning: Could not locate or create 'wedding_likes_db' Google Sheet in the target folder. Likes may not persist.")

# --- HANDLE QUERY PARAMS (Delete, Like, & ZIP actions) ---
params = st.query_params
del_id = params.get("delete_id")
like_id = params.get("like_id")

if del_id and drive_service:
    try:
        drive_service.files().delete(fileId=del_id).execute()
        if spreadsheet_id and sheets_service:
            remove_file_from_sheet(sheets_service, spreadsheet_id, del_id)
        st.success("Memory deleted!")
    except Exception as e:
        st.error(f"Delete failed: {e}")
    st.query_params.clear()
    st.rerun()

if like_id and sheets_service and spreadsheet_id:
    action = params.get("action", "like")
    delta = 1 if action == "like" else -1
    try:
        update_like_in_sheet(sheets_service, spreadsheet_id, like_id, delta)
    except Exception as e:
        st.error(f"Like update failed: {e}")
    st.query_params.clear()
    st.rerun()

st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite memories and browse the live gallery below.")
st.caption("✨ Tap photo to open | Tap heart to like | Double tap photo to like")

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
        if st.button("Submit to Wedding Album"):
            if not drive_service:
                st.error("Google services are not initialized. Check your secrets.")
            else:
                total_files = len(uploaded_files)
                progress_bar = st.progress(0)
                status_text = st.empty()
                success_count = 0
                failed_files = []
                
                clean_guest_name = guest_name.strip() if guest_name and guest_name.strip() else "Guest"
                newly_uploaded_ids = []
                
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
                                newly_uploaded_ids.append(file_id)
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
                    st.session_state.new_uploads = newly_uploaded_ids
                    st.session_state.upload_msg = f"Successfully uploaded {success_count} of {total_files} memories!"
                    st.session_state.uploader_key += 1
                    st.rerun()

with tab2:
    st.header("Wedding Gallery")
    
    # --- HANDLE ZIP ARCHIVE CREATION ---
    zip_ids_param = params.get("zip_ids")
    if zip_ids_param and drive_service:
        zip_ids = zip_ids_param.split(",")
        with st.spinner(f"Packaging {len(zip_ids)} memories into a ZIP folder..."):
            try:
                zip_buffer = io.BytesIO()
                creds = get_credentials()
                headers = {"Authorization": f"Bearer {creds.token}"}

                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fid in zip_ids:
                        for attempt in range(3):
                            try:
                                active_service = drive_service if attempt == 0 else create_drive_service()
                                f_meta = active_service.files().get(fileId=fid, fields="name").execute()
                                file_name = f_meta.get("name", f"wedding_memory_{fid}.jpg")

                                download_url = f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media"
                                res = requests.get(download_url, headers=headers, timeout=120)
                                
                                if res.status_code == 200:
                                    zf.writestr(file_name, res.content)
                                    break
                                else:
                                    raise Exception(f"HTTP {res.status_code}")
                            except Exception as dl_err:
                                if attempt == 2:
                                    st.warning(f"Could not include file {fid} in ZIP: {dl_err}")
                                time.sleep(1)
                
                zip_buffer.seek(0)
                st.success("Your ZIP folder is ready!")
                
                col_z1, col_z2 = st.columns([0.6, 0.4])
                with col_z1:
                    st.download_button(
                        label="💾 Save ZIP Folder",
                        data=zip_buffer,
                        file_name="wedding_memories.zip",
                        mime="application/zip",
                        type="primary"
                    )
                with col_z2:
                    if st.button("Close / Done"):
                        st.query_params.clear()
                        st.rerun()
                st.markdown("---")
            except Exception as e:
                st.error(f"Error creating ZIP: {e}")

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

            recent_uploads_json = "[]"
            if "new_uploads" in st.session_state:
                recent_uploads_json = json.dumps(st.session_state.new_uploads)
                del st.session_state.new_uploads

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                html_items = []
                for file in files:
                    fid = file.get('id')
                    raw_title = file.get('name', '')
                    mime = file.get('mimeType', '')
                    thumb_small = file.get('thumbnailLink', '').replace('=s220', '=s400')
                    full_image = file.get('thumbnailLink', '').replace('=s220', '=s1600')
                    preview_url = f"https://drive.google.com/file/d/{fid}/preview"
                    is_video = 'video' in mime or 'mp4' in mime or 'mov' in mime
                    
                    likes_count = int(likes_dict.get(fid, 0))
                    
                    if '_' in raw_title:
                        uploader_name = raw_title.split('_', 1)[0].strip()
                    else:
                        uploader_name = 'Guest'
                    if not uploader_name:
                        uploader_name = 'Guest'
                    
                    if not is_video and thumb_small:
                        media_content = f'<img src="{thumb_small}" alt="Photo" />'
                    else:
                        media_content = '<div class="video-label">▶ Video</div>'
                        
                    html_items.append(f'''
                    <div class="grid-card" id="card-{fid}" data-fid="{fid}">
                        <input type="checkbox" class="select-check" data-id="{fid}" onclick="updateCount(event)" />
                        <a href="?like_id={fid}&action=like" target="_top" class="like-btn" id="like-btn-{fid}" title="Like memory" onclick="handleLikeClick(event, \'{fid}\')">
                            ❤️ <span id="like-count-{fid}">{likes_count}</span>
                        </a>
                        <a href="?delete_id={fid}" target="_top" class="delete-btn" id="del-btn-{fid}" title="Delete Photo" onclick="return handleDeleteClick(event, \'{fid}\')" style="display:none;">🗑️</a>
                        <div class="card-link" onclick="handleCardClick(event, \'{fid}\', \'{full_image}\', \'{preview_url}\', {'true' if is_video else 'false'})">
                            {media_content}
                        </div>
                        <div class="uploader-tag">Added by {uploader_name}</div>
                    </div>
                    ''')

                gallery_html = f'''
                <!DOCTYPE html>
                <html>
                <head>
                <style>
                    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                    body {{ background: transparent; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                    
                    .gallery-grid {{
                        display: grid !important;
                        grid-template-columns: repeat(3, 1fr) !important;
                        gap: 6px !important;
                        width: 100% !important;
                    }}
                    
                    .grid-card {{
                        position: relative;
                        width: 100%;
                        aspect-ratio: 1 / 1;
                        background: #111;
                        border-radius: 6px;
                        overflow: hidden;
                        cursor: pointer;
                        user-select: none;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.15);
                    }}
                    
                    .card-link {{
                        display: block;
                        width: 100%;
                        height: 100%;
                    }}
                    
                    .grid-card img {{
                        width: 100%;
                        height: 100%;
                        object-fit: cover;
                        display: block;
                    }}
                    
                    .video-label {{
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100%;
                        color: #fff;
                        font-size: 12px;
                        background: #222;
                        font-weight: 500;
                    }}
                    
                    .uploader-tag {{
                        position: absolute;
                        bottom: 0;
                        left: 0;
                        right: 0;
                        background: rgba(0, 0, 0, 0.75);
                        color: #ffffff;
                        font-size: 10px;
                        padding: 4px 6px;
                        text-align: center;
                        white-space: nowrap;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        pointer-events: none;
                        z-index: 5;
                    }}
                    
                    .select-check {{
                        position: absolute;
                        top: 8px;
                        left: 8px;
                        z-index: 10;
                        width: 22px;
                        height: 22px;
                        accent-color: #1a73e8;
                        cursor: pointer;
                    }}

                    .like-btn {{
                        position: absolute;
                        top: 8px;
                        left: 50%;
                        transform: translateX(-50%);
                        z-index: 10;
                        background: rgba(0, 0, 0, 0.65);
                        border: 1px solid rgba(255, 255, 255, 0.8);
                        border-radius: 12px;
                        color: #ffffff;
                        font-size: 11px;
                        padding: 3px 8px;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        gap: 3px;
                        line-height: 1;
                        font-family: inherit;
                        text-decoration: none;
                        transition: transform 0.15s ease, background 0.15s ease;
                    }}
                    
                    .like-btn.liked {{
                        background: rgba(225, 29, 72, 0.9);
                        border-color: #ff4d6d;
                        transform: translateX(-50%) scale(1.08);
                    }}

                    @keyframes heartBurst {{
                        0% {{ opacity: 1; transform: translate(-50%, -50%) scale(0.3); }}
                        50% {{ opacity: 1; transform: translate(-50%, -80%) scale(1.5); }}
                        100% {{ opacity: 0; transform: translate(-50%, -120%) scale(2.0); }}
                    }}

                    .pop-heart {{
                        position: absolute;
                        top: 50%;
                        left: 50%;
                        font-size: 42px;
                        pointer-events: none;
                        z-index: 25;
                        animation: heartBurst 0.65s cubic-bezier(0.17, 0.89, 0.32, 1.28) forwards;
                    }}

                    .delete-btn {{
                        position: absolute;
                        top: 8px;
                        right: 8px;
                        z-index: 10;
                        width: 24px;
                        height: 24px;
                        border-radius: 50%;
                        background: rgba(0, 0, 0, 0.7);
                        border: 1px solid rgba(255, 255, 255, 0.8);
                        color: white;
                        font-size: 11px;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        text-decoration: none;
                    }}
                    
                    .action-bar {{
                        margin-top: 14px;
                        padding: 10px 16px;
                        background: #1e1e1e;
                        border-radius: 8px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        color: #fff;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                    }}
                    
                    .dl-btn {{
                        background: #1a73e8;
                        color: #fff;
                        border: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: bold;
                        cursor: pointer;
                    }}
                    .dl-btn:disabled {{
                        background: #444;
                        color: #888;
                        cursor: not-allowed;
                    }}
                </style>
                </head>
                <body>
                    <div class="gallery-grid">
                        {"".join(html_items)}
                    </div>
                    
                    <div class="action-bar">
                        <span id="count-text">0 items selected</span>
                        <button id="dl-btn" class="dl-btn" onclick="prepareZipDownload()" disabled>📦 Download ZIP</button>
                    </div>

                    <script>
                        let clickTimers = {{}};
                        let tapCounts = {{}};

                        function getMyUploads() {{
                            try {{
                                return JSON.parse(window.localStorage.getItem('my_wedding_uploads') || '[]');
                            }} catch(e) {{
                                return [];
                            }}
                        }}

                        function getLikedItems() {{
                            try {{
                                return JSON.parse(window.localStorage.getItem('liked_wedding_photos') || '[]');
                            }} catch(e) {{
                                return [];
                            }}
                        }}

                        function setLikedItems(items) {{
                            try {{
                                window.localStorage.setItem('liked_wedding_photos', JSON.stringify(items));
                            }} catch(e) {{}}
                        }}

                        function initApp() {{
                            let mine = getMyUploads();
                            const newlyUploaded = {recent_uploads_json};
                            if (newlyUploaded && newlyUploaded.length > 0) {{
                                newlyUploaded.forEach(id => {{
                                    if (!mine.includes(id)) mine.push(id);
                                }});
                                try {{
                                    window.localStorage.setItem('my_wedding_uploads', JSON.stringify(mine));
                                }} catch(e) {{}}
                            }}

                            mine.forEach(fid => {{
                                const delBtn = document.getElementById('del-btn-' + fid);
                                if (delBtn) delBtn.style.display = 'flex';
                            }});

                            const liked = getLikedItems();
                            liked.forEach(fid => {{
                                const btn = document.getElementById('like-btn-' + fid);
                                if (btn) btn.classList.add('liked');
                            }});
                        }}

                        initApp();

                        function handleLikeClick(e, fid) {{
                            if (e) e.stopPropagation();

                            const card = document.getElementById('card-' + fid);
                            const countSpan = document.getElementById('like-count-' + fid);
                            const likeBtn = document.getElementById('like-btn-' + fid);

                            let likedList = getLikedItems();
                            const alreadyLiked = likedList.includes(fid);
                            let action = "like";

                            if (!alreadyLiked) {{
                                likedList.push(fid);
                                setLikedItems(likedList);
                                action = "like";

                                if (card) {{
                                    const burst = document.createElement('div');
                                    burst.className = 'pop-heart';
                                    burst.innerText = '❤️';
                                    card.appendChild(burst);
                                    setTimeout(() => burst.remove(), 650);
                                }}
                                if (likeBtn) likeBtn.classList.add('liked');
                                if (countSpan) {{
                                    const cur = parseInt(countSpan.innerText || '0');
                                    countSpan.innerText = cur + 1;
                                }}
                            }} else {{
                                likedList = likedList.filter(id => id !== fid);
                                setLikedItems(likedList);
                                action = "unlike";

                                if (likeBtn) likeBtn.classList.remove('liked');
                                if (countSpan) {{
                                    const cur = parseInt(countSpan.innerText || '0');
                                    countSpan.innerText = Math.max(0, cur - 1);
                                }}
                            }}

                            // Update the link href dynamically before top-level navigation occurs
                            e.currentTarget.href = '?like_id=' + fid + '&action=' + action + '&_t=' + Date.now();
                        }}

                        function handleDeleteClick(e, fid) {{
                            if (e) e.stopPropagation();
                            if (!confirm("Delete this photo from the album?")) {{
                                return false;
                            }}
                            let mine = getMyUploads();
                            mine = mine.filter(id => id !== fid);
                            try {{
                                window.localStorage.setItem('my_wedding_uploads', JSON.stringify(mine));
                            }} catch(e) {{}}
                            return true;
                        }}

                        function handleCardClick(e, fid, fullImg, previewUrl, isVideo) {{
                            if (e) e.stopPropagation();
                            
                            tapCounts[fid] = (tapCounts[fid] || 0) + 1;

                            if (tapCounts[fid] === 1) {{
                                clickTimers[fid] = setTimeout(() => {{
                                    tapCounts[fid] = 0;
                                    openModal(fullImg, previewUrl, isVideo);
                                }}, 260);
                            }} else if (tapCounts[fid] === 2) {{
                                clearTimeout(clickTimers[fid]);
                                tapCounts[fid] = 0;
                                // Trigger like click programmatically
                                const likeBtn = document.getElementById('like-btn-' + fid);
                                if (likeBtn) {{
                                    likeBtn.click();
                                }}
                            }}
                        }}

                        function openModal(fullImg, previewUrl, isVideo) {{
                            const parentWin = window.top || window.parent;
                            const parentDoc = parentWin.document;
                            
                            parentWin.closeWeddingModal = function() {{
                                const overlay = parentDoc.getElementById('global-wedding-lightbox');
                                if (overlay) {{
                                    overlay.style.display = 'none';
                                    overlay.innerHTML = '';
                                }}
                            }};

                            let overlay = parentDoc.getElementById('global-wedding-lightbox');
                            
                            if (!overlay) {{
                                overlay = parentDoc.createElement('div');
                                overlay.id = 'global-wedding-lightbox';
                                overlay.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.88); z-index:9999999; display:none; justify-content:center; align-items:center;';
                                parentDoc.body.appendChild(overlay);
                            }}

                            overlay.onclick = function(e) {{
                                if (e.target === overlay) {{
                                    parentWin.closeWeddingModal();
                                }}
                            }};

                            overlay.innerHTML = '';

                            const closeBtn = parentDoc.createElement('button');
                            closeBtn.id = 'wedding-modal-close-btn';
                            closeBtn.innerHTML = '✕';
                            closeBtn.style.cssText = 'position:fixed; top:20px; right:20px; color:#ffffff; font-size:26px; font-weight:bold; cursor:pointer; background:rgba(20,20,20,0.85); border:2px solid #ffffff; border-radius:50%; width:46px; height:46px; display:flex; align-items:center; justify-content:center; z-index:10000000; box-shadow:0 4px 12px rgba(0,0,0,0.6); line-height:1; font-family:sans-serif;';
                            
                            closeBtn.onclick = function(e) {{
                                e.stopPropagation();
                                parentWin.closeWeddingModal();
                            }};

                            const mediaContainer = parentDoc.createElement('div');
                            mediaContainer.style.cssText = 'position:relative; max-width:85vw; max-height:85vh; display:flex; justify-content:center; align-items:center;';

                            if (isVideo) {{
                                const iframe = parentDoc.createElement('iframe');
                                iframe.src = previewUrl;
                                iframe.style.cssText = 'width:80vw; height:75vh; max-width:80vw; max-height:80vh; border:none; border-radius:8px; background:#000; box-shadow:0 8px 30px rgba(0,0,0,0.6);';
                                iframe.allow = 'autoplay';
                                mediaContainer.appendChild(iframe);
                            }} else {{
                                const img = parentDoc.createElement('img');
                                img.src = fullImg;
                                img.style.cssText = 'max-width:80vw; max-height:80vh; width:auto; height:auto; object-fit:contain; border-radius:8px; box-shadow:0 8px 30px rgba(0,0,0,0.6);';
                                mediaContainer.appendChild(img);
                            }}

                            overlay.appendChild(closeBtn);
                            overlay.appendChild(mediaContainer);
                            overlay.style.display = 'flex';

                            parentWin.onkeydown = function(e) {{
                                if (e.key === 'Escape') {{
                                    parentWin.closeWeddingModal();
                                }}
                            }};
                        }}

                        function updateCount(e) {{
                            if (e) e.stopPropagation();
                            const checked = document.querySelectorAll('.select-check:checked');
                            const countText = document.getElementById('count-text');
                            const btn = document.getElementById('dl-btn');
                            countText.innerText = checked.length + " item(s) selected";
                            btn.disabled = checked.length === 0;
                        }}

                        function prepareZipDownload() {{
                            const checked = document.querySelectorAll('.select-check:checked');
                            const ids = [];
                            checked.forEach(cb => {{
                                ids.push(cb.getAttribute('data-id'));
                            }});
                            if (ids.length > 0) {{
                                const link = document.createElement('a');
                                link.href = '?zip_ids=' + ids.join(',') + '&_t=' + Date.now();
                                link.target = '_top';
                                document.body.appendChild(link);
                                link.click();
                                link.remove();
                            }}
                        }}
                    </script>
                </body>
                </html>
                '''
                
                grid_rows = (len(files) + 2) // 3
                calculated_height = (grid_rows * 145) + 90
                st.components.v1.html(gallery_html, height=calculated_height, scrolling=False)

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

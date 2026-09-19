import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import socket
import ssl
import time

st.set_page_config(
    page_title="Jamie & Millie's Wedding Album",
    page_icon="💍",
    layout="wide"
)

TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []
if 'selected_files' not in st.session_state:
    st.session_state.selected_files = set()

# CSS for a true Google Photos style 3-column grid with inline thumbnail overlays
st.markdown("""
<style>
    .main .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        max-width: 100% !important;
    }
    .google-photos-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 4px;
        width: 100%;
        margin-bottom: 20px;
    }
    .photo-card {
        position: relative;
        background-color: #111;
        border-radius: 4px;
        overflow: hidden;
        aspect-ratio: 1 / 1;
        width: 100%;
    }
    .photo-card img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .video-badge {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        background: #222;
        color: white;
        font-size: 12px;
    }
</style>
""", unsafe_allow_html=True)

st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite moments and browse live memories below.")

@st.cache_resource
def get_google_services():
    try:
        creds = Credentials(
            token=None,
            refresh_token=st.secrets["refresh_token"],
            client_id=st.secrets["client_id"],
            client_secret=st.secrets["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
        )
        drive_service = build('drive', 'v3', credentials=creds)
        return drive_service
    except Exception as e:
        st.error(f"Failed to authenticate with Google: {e}")
        return None

drive_service = get_google_services()

tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Gallery"])

with tab1:
    st.header("Upload Photos & Videos")
    st.write("Tap below to choose files from your phone library or camera:")
    
    uploaded_files = st.file_uploader(
        "Choose files from gallery", 
        type=["jpg", "jpeg", "png", "heic", "mp4", "mov"],
        accept_multiple_files=True,
        label_visibility="collapsed"
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
                
                for index, uploaded_file in enumerate(uploaded_files):
                    status_text.text(f"Uploading {index + 1} of {total_files}: {uploaded_file.name}...")
                    uploaded_successfully = False
                    last_err = None
                    
                    for attempt in range(3):
                        try:
                            file_metadata = {
                                'name': f"{guest_name or 'Guest'}_{uploaded_file.name}",
                                'parents': [TARGET_FOLDER_ID]
                            }
                            media = MediaIoBaseUpload(
                                io.BytesIO(uploaded_file.getvalue()),
                                mimetype=uploaded_file.type or 'application/octet-stream',
                                resumable=True
                            )
                            file = drive_service.files().create(
                                body=file_metadata,
                                media_body=media,
                                fields='id'
                            ).execute()
                            file_id = file.get('id')
                            if file_id and file_id not in st.session_state.my_uploads:
                                st.session_state.my_uploads.append(file_id)
                            uploaded_successfully = True
                            success_count += 1
                            break
                        except (ssl.SSLError, socket.timeout, Exception) as e:
                            last_err = e
                            time.sleep(1)
                    
                    if not uploaded_successfully:
                        failed_files.append((uploaded_file.name, str(last_err)))
                    progress_bar.progress((index + 1) / total_files)
                
                status_text.empty()
                progress_bar.empty()
                if success_count > 0:
                    st.success(f"Successfully uploaded {success_count} of {total_files} memories!")
                if failed_files:
                    st.error(f"Failed to upload {len(failed_files)} file(s):")
                    for fname, err in failed_files:
                        st.write(f"- **{fname}**: {err}")

with tab2:
    st.header("Wedding Gallery")
    
    if drive_service:
        try:
            query = f"'{TARGET_FOLDER_ID}' in parents and trashed=false"
            results = None
            for attempt in range(3):
                try:
                    results = drive_service.files().list(
                        q=query,
                        pageSize=100,
                        fields="files(id, name, webViewLink, webContentLink, thumbnailLink, mimeType)",
                        orderBy="createdTime desc"
                    ).execute()
                    break
                except (ssl.SSLError, socket.timeout, Exception) as net_err:
                    if attempt == 2:
                        raise net_err
                    time.sleep(1)
            
            files = results.get('files', []) if results else []

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                # Top action bar if any items are selected
                active_selected = list(st.session_state.selected_files)
                if active_selected:
                    st.markdown("---")
                    col_b1, col_b2 = st.columns([0.5, 0.5])
                    with col_b1:
                        st.write(f"**{len(active_selected)} items selected**")
                    with col_b2:
                        if st.button("📥 Download Selected"):
                            js_code = ""
                            for i, fid in enumerate(active_selected):
                                matched = next((f for f in files if f['id'] == fid), None)
                                if matched and matched.get('webContentLink'):
                                    link = matched['webContentLink']
                                    js_code += f"setTimeout(function(){{ window.open('{link}', '_blank'); }}, {i * 400});"
                            if js_code:
                                st.components.v1.html(f"<script>{js_code}</script>", height=0)
                                st.success("Downloading straight to your device folder...")
                    st.markdown("---")

                # Render grid layout using Streamlit columns natively so checkboxes live seamlessly right under each photo without page jumps
                for i in range(0, len(files), 3):
                    row_files = files[i:i+3]
                    cols = st.columns(3)
                    
                    for idx, file in enumerate(row_files):
                        with cols[idx]:
                            file_id = file.get('id')
                            mime_type = file.get('mimeType', '')
                            thumb_link = file.get('thumbnailLink')
                            web_link = file.get('webViewLink', '#')
                            is_mine = file_id in st.session_state.my_uploads
                            
                            # Thumbnail container
                            if 'image' in mime_type and thumb_link:
                                img_src = thumb_link.replace('=s220', '=s400')
                                st.markdown(f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank" style="position:absolute; width:100%; height:100%; z-index:2;"></a>
                                    <img src="{img_src}" alt="Memory">
                                </div>
                                ''', unsafe_allow_html=True)
                            else:
                                st.markdown(f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank" style="position:absolute; width:100%; height:100%; z-index:2;"></a>
                                    <div class="video-badge">▶ Video</div>
                                </div>
                                ''', unsafe_allow_html=True)
                            
                            # Compact controls right below each individual thumbnail
                            c_sel, c_del = st.columns([0.7, 0.3])
                            with c_sel:
                                is_checked = st.checkbox("Select", key=f"sel_{file_id}", label_visibility="collapsed")
                                if is_checked:
                                    if file_id not in st.session_state.selected_files:
                                      st.session_state.selected_files.add(file_id)
                                else:
                                    if file_id in st.session_state.selected_files:
                                      st.session_state.selected_files.remove(file_id)
                            with c_del:
                                if is_mine:
                                    if st.button("🗑️", key=f"del_{file_id}", help="Delete your upload"):
                                        drive_service.files().delete(fileId=file_id).execute()
                                        if file_id in st.session_state.my_uploads:
                                            st.session_state.my_uploads.remove(file_id)
                                        if file_id in st.session_state.selected_files:
                                            st.session_state.selected_files.remove(file_id)
                                        st.rerun()

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

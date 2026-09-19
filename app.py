import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import socket
import ssl
import time

# Page configuration
st.set_page_config(
    page_title="Jamie & Millie's Wedding Album",
    page_icon="💍",
    layout="wide"
)

# Target Google Drive Folder
TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

# Session state initialization
if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []

# --- CUSTOM CSS: NATIVE OVERLAY CONTROLS + ZERO-SCROLL MOBILE 3-COLUMN GRID ---
st.markdown("""
<style>
    /* Prevent horizontal page scrolling on mobile viewports */
    html, body, .stApp, .main, .block-container {
        overflow-x: hidden !important;
        max-width: 100vw !important;
    }
    .main .block-container {
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
        padding-top: 1rem !important;
    }

    /* Force Streamlit 3-column rows to fit strictly within 100% width */
    [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 3px !important;
        width: 100% !important;
        margin-bottom: 3px !important;
    }
    
    [data-testid="column"] {
        position: relative !important;
        flex: 1 1 0% !important;
        min-width: 0 !important;
        padding: 0 !important;
    }

    /* Square photo card container */
    .photo-card {
        position: relative;
        width: 100%;
        aspect-ratio: 1 / 1;
        border-radius: 4px;
        overflow: hidden;
        background: #111;
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
        font-size: 11px;
    }
    .view-link {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 1;
    }

    /* OVERLAY 1: Top-Left Checkbox */
    [data-testid="column"] [data-testid="stCheckbox"] {
        position: absolute !important;
        top: 4px !important;
        left: 4px !important;
        z-index: 10 !important;
        background: rgba(0, 0, 0, 0.4);
        border-radius: 50%;
        padding: 2px !important;
        margin: 0 !important;
    }
    [data-testid="column"] [data-testid="stCheckbox"] label p {
        display: none !important; /* Hide text label */
    }

    /* OVERLAY 2: Top-Right Delete Button */
    [data-testid="column"] [data-testid="stElementContainer"]:has([data-testid="stButton"]) {
        position: absolute !important;
        top: 4px !important;
        right: 4px !important;
        z-index: 10 !important;
        width: auto !important;
    }
    [data-testid="column"] button {
        background: rgba(0, 0, 0, 0.6) !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.8) !important;
        border-radius: 50% !important;
        width: 24px !important;
        height: 24px !important;
        min-width: 24px !important;
        min-height: 24px !important;
        padding: 0 !important;
        font-size: 11px !important;
        line-height: 1 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
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
                active_selected_links = []
                
                # Render photos in rows of 3 columns
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
                            
                            # 1. Base Thumbnail
                            if 'image' in mime_type and thumb_link:
                                img_src = thumb_link.replace('=s220', '=s400')
                                card_html = f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank" class="view-link"></a>
                                    <img src="{img_src}" alt="Memory">
                                </div>
                                '''
                            else:
                                card_html = f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank" class="view-link"></a>
                                    <div class="video-badge">▶ Video</div>
                                </div>
                                '''
                            st.markdown(card_html, unsafe_allow_html=True)
                            
                            # 2. Overlay Top-Left Checkbox
                            is_checked = st.checkbox("", key=f"sel_{file_id}", label_visibility="collapsed")
                            if is_checked and file.get('webContentLink'):
                                active_selected_links.append(file['webContentLink'])
                            
                            # 3. Overlay Top-Right Delete Button (for user's own uploads)
                            if is_mine:
                                if st.button("✕", key=f"del_{file_id}", help="Delete photo"):
                                    drive_service.files().delete(fileId=file_id).execute()
                                    if file_id in st.session_state.my_uploads:
                                        st.session_state.my_uploads.remove(file_id)
                                    st.rerun()

                # Action Bar for Download
                if active_selected_links:
                    st.markdown("---")
                    col_b1, col_b2 = st.columns([0.5, 0.5])
                    with col_b1:
                        st.write(f"**{len(active_selected_links)} selected**")
                    with col_b2:
                        if st.button("📥 Download Selected"):
                            js_code = ""
                            for i, link in enumerate(active_selected_links):
                                js_code += f"setTimeout(function(){{ window.open('{link}', '_blank'); }}, {i * 400});"
                            if js_code:
                                st.components.v1.html(f"<script>{js_code}</script>", height=0)
                                st.success("Downloading straight to your device folder...")

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

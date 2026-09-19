import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import socket
import ssl

# Page configuration
st.set_page_config(
    page_title="Jamie & Millie's Wedding Media Uploader",
    page_icon="💍",
    layout="wide"
)

# --- TARGET GOOGLE DRIVE FOLDER ID ---
TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

# --- INITIALIZE SESSION STATE FOR DEVICE TRACKING ---
if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []

# --- CUSTOM CSS: FORCE 3 COLUMNS ON MOBILE & GOOGLE PHOTOS STYLE ---
st.markdown("""
<style>
    /* Force Streamlit columns to stay 3-across even on mobile screens */
    [data-testid="column"] {
        width: 33.333% !important;
        flex: 1 1 33.333% !important;
        min-width: 33.333% !important;
        padding: 3px !important;
    }
    .photo-card {
        position: relative;
        background-color: #111;
        border-radius: 6px;
        overflow: hidden;
        aspect-ratio: 1 / 1;
        margin-bottom: 5px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }
    .photo-card img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 6px;
    }
    .video-badge {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        background: #222;
        color: white;
        font-size: 20px;
        border-radius: 6px;
    }
    .card-actions {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 11px;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- PERSONAL TOUCH: TITLE ---
st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite moments and browse the live gallery below.")

# --- GOOGLE API AUTHENTICATION ---
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
        sheets_service = build('sheets', 'v4', credentials=creds)
        return drive_service, sheets_service
    except Exception as e:
        st.error(f"Failed to authenticate with Google: {e}")
        return None, None

drive_service, sheets_service = get_google_services()

# --- TAB LAYOUT ---
tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Gallery"])

with tab1:
    st.header("Upload Photos & Videos")
    st.write("Tap below to open your phone's photo library, camera, or files:")
    
    uploaded_files = st.file_uploader(
        "Choose files from gallery", 
        type=None,
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
                for index, uploaded_file in enumerate(uploaded_files):
                    status_text.text(f"Uploading {index + 1} of {total_files}: {uploaded_file.name}...")
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
                        if file_id not in st.session_state.my_uploads:
                            st.session_state.my_uploads.append(file_id)
                            
                        success_count += 1
                    except Exception as e:
                        st.error(f"Failed to upload {uploaded_file.name}: {e}")
                    
                    progress_bar.progress((index + 1) / total_files)
                
                status_text.empty()
                progress_bar.empty()
                st.success(f"Successfully uploaded {success_count} of {total_files} memories!")

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
            
            files = results.get('files', []) if files else []

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                selected_files = []

                # --- TOP BATCH DOWNLOAD ACTION BAR ---
                # Check session state for all file selections
                active_selected_links = []
                for file in files:
                    fid = file['id']
                    if st.session_state.get(f"sel_{fid}", False):
                        if file.get('webContentLink'):
                            active_selected_links.append(file['webContentLink'])

                if active_selected_links:
                    st.markdown("---")
                    col_b1, col_b2 = st.columns([0.6, 0.4])
                    with col_b1:
                        st.write(f"**{len(active_selected_links)} items selected**")
                    with col_b2:
                        if st.button("📥 Download Selected"):
                            # Sequential JavaScript trigger to drop files straight into downloads folder
                            js_code = ""
                            for i, link in enumerate(active_selected_links):
                                js_code += f"setTimeout(function(){{ window.open('{link}', '_blank'); }}, {i * 400});"
                            st.components.v1.html(f"<script>{js_code}</script>", height=0)
                            st.success("Downloading selected items to your device folder...")
                    st.markdown("---")

                # --- 3-COLUMN UNIFORM GRID ---
                grid_cols = st.columns(3)
                for idx, file in enumerate(files):
                    g_col = grid_cols[idx % 3]
                    with g_col:
                        try:
                            file_id = file.get('id')
                            mime_type = file.get('mimeType', '')
                            thumb_link = file.get('thumbnailLink')
                            web_link = file.get('webViewLink', '#')
                            is_mine = file_id in st.session_state.my_uploads
                            
                            # Thumbnail Media View (Clicking image opens full view in new tab without downloading)
                            if 'image' in mime_type and thumb_link:
                                img_src = thumb_link.replace('=s220', '=s600')
                                thumbnail_html = f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank">
                                        <img src="{img_src}" alt="Memory">
                                    </a>
                                </div>
                                '''
                            else:
                                thumbnail_html = f'''
                                <div class="photo-card">
                                    <a href="{web_link}" target="_blank" style="text-decoration:none;">
                                        <div class="video-badge">▶</div>
                                    </a>
                                </div>
                                '''
                            
                            st.markdown(thumbnail_html, unsafe_allow_html=True)
                            
                            # Compact selection checkbox and optional delete button right under thumbnail
                            act_c1, act_c2 = st.columns([0.7, 0.3])
                            with act_c1:
                                st.checkbox("Select", key=f"sel_{file_id}", label_visibility="collapsed")
                            with act_c2:
                                if is_mine:
                                    if st.button("❌", key=f"del_{file_id}", help="Delete your upload"):
                                        for del_attempt in range(3):
                                            try:
                                                drive_service.files().delete(fileId=file_id).execute()
                                                break
                                            except Exception:
                                                if del_attempt == 2:
                                                    raise
                                        if file_id in st.session_state.my_uploads:
                                            st.session_state.my_uploads.remove(file_id)
                                        st.rerun()

                        except Exception:
                            pass

        except Exception as e:
            st.warning("Connection hiccup communicating with Google Drive. Please refresh the page.")

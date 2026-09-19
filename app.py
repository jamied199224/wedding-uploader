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

# --- CUSTOM CSS FOR GOOGLE PHOTOS GRID & MOBILE OPTIMIZATION ---
st.markdown("""
<style>
    /* Clean Google Photos Style Uniform Grid */
    .gallery-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
        gap: 8px;
        margin-bottom: 20px;
    }
    .photo-card {
        position: relative;
        background-color: #f0f0f0;
        border-radius: 8px;
        overflow: hidden;
        aspect-ratio: 1 / 1;
        cursor: pointer;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        user-select: none;
    }
    .photo-card img, .photo-card video {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 8px;
    }
    .video-overlay {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        background: #111;
        color: white;
        font-size: 24px;
        border-radius: 8px;
    }
    /* Selection Overlay Checkmark */
    .select-checkbox {
        position: absolute;
        top: 6px;
        left: 6px;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 2px solid white;
        background: rgba(0,0,0,0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 12px;
        font-weight: bold;
        z-index: 5;
    }
    .photo-card.selected .select-checkbox {
        background: #0275d8;
        border-color: #0275d8;
    }
    /* Thumbnail Delete Button */
    .delete-btn {
        position: absolute;
        top: 6px;
        right: 6px;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: rgba(0,0,0,0.6);
        color: white;
        border: none;
        font-size: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        z-index: 5;
    }
</style>
""", unsafe_allow_html=True)

# --- PERSONAL TOUCH: TITLE ---
st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite moments from your phone's gallery and browse live memories below.")

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
    st.write("Tap below to open your phone's photo library, camera, or video records:")
    
    # Native mobile file picker configuration prompting camera/gallery sources
    uploaded_files = st.file_uploader(
        "Choose files from gallery", 
        type=None,  # Accepts all media types to trigger native mobile media selection prompt
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
            
            files = results.get('files', []) if results else []

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                st.write("✨ **Tip:** Tap items to select them, then use the download button at the top. Click a thumbnail to view full screen.")
                
                # Container for interactive gallery state management
                selected_ids = st.session_state.get('selected_gallery_ids', [])

                # Top Action Bar when items are selected
                if selected_ids:
                    col_act1, col_act2 = st.columns([0.7, 0.3])
                    with col_act1:
                        st.info(f"**{len(selected_ids)} items selected**")
                    with col_act2:
                        if st.button("📥 Download Selected"):
                            # Build sequential JavaScript download triggers for the user's browser downloads folder
                            js_downloads = ""
                            for fid in selected_ids:
                                matched_file = next((f for f in files if f['id'] == fid), None)
                                if matched_file and matched_file.get('webContentLink'):
                                    dl_link = matched_file['webContentLink']
                                    js_downloads += f"setTimeout(function(){{ window.open('{dl_link}', '_blank'); }}, 300 * {selected_ids.index(fid)});"
                            
                            if js_downloads:
                                st.components.v1.html(f"<script>{js_downloads}</script>", height=0)
                                st.success("Downloading selected files to your device folder...")

                    if st.button("Clear Selection"):
                        st.session_state['selected_gallery_ids'] = []
                        st.rerun()
                    st.markdown("---")

                # Render Google Photos style uniform grid using columns
                grid_cols = st.columns(3)
                for idx, file in enumerate(files):
                    g_col = grid_cols[idx % 3]
                    with g_col:
                        try:
                            file_id = file.get('id')
                            file_name = file.get('name', 'Memory')
                            mime_type = file.get('mimeType', '')
                            thumb_link = file.get('thumbnailLink')
                            web_link = file.get('webViewLink', '#')
                            is_mine = file_id in st.session_state.my_uploads
                            is_selected = file_id in selected_ids
                            
                            # Thumbnail Media Preview HTML
                            if 'image' in mime_type and thumb_link:
                                img_src = thumb_link.replace('=s220', '=s600')
                                media_html = f'<img src="{img_src}" alt="Memory">'
                            else:
                                media_html = '<div class="video-overlay">▶</div>'
                            
                            # Card HTML container
                            card_class = "photo-card selected" if is_selected else "photo-card"
                            
                            # Render interactive thumbnail card
                            st.markdown(f'''
                            <div class="{card_class}" id="card_{file_id}" onclick="
                                event.preventDefault();
                                window.location.href = '?select_id={file_id}';
                            ">
                                <a href="{web_link}" target="_blank" title="Click to view full size" style="position: absolute; width:100%; height:100%; top:0; left:0; z-index:1;"></a>
                                {media_html}
                                <div class="select-checkbox">{"✓" if is_selected else ""}</div>
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            # Handle selection toggle via query parameters or buttons safely in Streamlit state
                            # (A secondary delete button if it belongs to the user session)
                            if is_mine:
                                if st.button("❌ Remove", key=f"del_{file_id}", help="Delete your upload"):
                                    for del_attempt in range(3):
                                        try:
                                            drive_service.files().delete(fileId=file_id).execute()
                                            break
                                        except Exception:
                                            if del_attempt == 2:
                                                raise
                                    if file_id in st.session_state.my_uploads:
                                        st.session_state.my_uploads.remove(file_id)
                                    if file_id in selected_ids:
                                        selected_ids.remove(file_id)
                                        st.session_state['selected_gallery_ids'] = selected_ids
                                    st.rerun()

                        except Exception:
                            pass

        except Exception as e:
            st.warning("Connection hiccup communicating with Google Drive. Please refresh the page.")

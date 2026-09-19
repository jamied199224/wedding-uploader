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
                # Custom HTML component rendering a rigid CSS 3-column grid with native overlays
                html_items = []
                for file in files:
                    fid = file.get('id')
                    mime = file.get('mimeType', '')
                    thumb = file.get('thumbnailLink', '').replace('=s220', '=s400')
                    view_url = file.get('webViewLink', '#')
                    dl_url = file.get('webContentLink', '#')
                    
                    if 'image' in mime and thumb:
                        media_content = f'<img src="{thumb}" alt="Photo" />'
                    else:
                        media_content = '<div class="video-label">▶ Video</div>'
                        
                    html_items.append(f'''
                    <div class="grid-card">
                        <input type="checkbox" class="select-check" data-dl="{dl_url}" onclick="updateCount()" />
                        <a href="{view_url}" target="_blank" class="card-link">{media_content}</a>
                    </div>
                    ''')

                gallery_html = f'''
                <!DOCTYPE html>
                <html>
                <head>
                <style>
                    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                    body {{ background: transparent; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                    
                    /* STRICT 3-COLUMN GRID locked across all mobile viewports */
                    .gallery-grid {{
                        display: grid !important;
                        grid-template-columns: repeat(3, 1fr) !important;
                        gap: 4px !important;
                        width: 100% !important;
                    }}
                    
                    .grid-card {{
                        position: relative;
                        width: 100%;
                        aspect-ratio: 1 / 1;
                        background: #111;
                        border-radius: 4px;
                        overflow: hidden;
                    }}
                    
                    .card-link {{
                        display: block;
                        width: 100%;
                        height: 100%;
                        text-decoration: none;
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
                        font-size: 11px;
                        background: #222;
                    }}
                    
                    /* TOP-LEFT OVERLAY CHECKBOX */
                    .select-check {{
                        position: absolute;
                        top: 6px;
                        left: 6px;
                        z-index: 10;
                        width: 20px;
                        height: 20px;
                        accent-color: #ff4b4b;
                        cursor: pointer;
                    }}
                    
                    /* ACTION BAR */
                    .action-bar {{
                        margin-top: 12px;
                        padding: 10px;
                        background: #1e1e1e;
                        border-radius: 8px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        color: #fff;
                    }}
                    
                    .dl-btn {{
                        background: #ff4b4b;
                        color: #fff;
                        border: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        font-weight: bold;
                        cursor: pointer;
                    }}
                    .dl-btn:disabled {{
                        background: #555;
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
                        <button id="dl-btn" class="dl-btn" onclick="downloadSelected()" disabled>📥 Download</button>
                    </div>

                    <script>
                        function updateCount() {{
                            const checked = document.querySelectorAll('.select-check:checked');
                            const countText = document.getElementById('count-text');
                            const btn = document.getElementById('dl-btn');
                            countText.innerText = checked.length + " item(s) selected";
                            btn.disabled = checked.length === 0;
                        }}

                        function downloadSelected() {{
                            const checked = document.querySelectorAll('.select-check:checked');
                            checked.forEach((cb, i) => {{
                                const url = cb.getAttribute('data-dl');
                                if (url && url !== '#') {{
                                    setTimeout(() => {{
                                        window.open(url, '_blank');
                                    }}, i * 300);
                                }}
                            }});
                        }}
                    </script>
                </body>
                </html>
                '''
                
                # Render gallery frame with calculated dynamic height
                grid_rows = (len(files) + 2) // 3
                calculated_height = (grid_rows * 130) + 80
                st.components.v1.html(gallery_html, height=calculated_height, scrolling=False)

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

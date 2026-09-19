import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import io
import socket
import ssl
import time
import zipfile

st.set_page_config(
    page_title="Jamie & Millie's Wedding Album",
    page_icon="💍",
    layout="wide"
)

TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []

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

# --- HANDLE QUERY PARAMS (Delete actions) ---
params = st.query_params

if "delete_id" in params and drive_service:
    del_id = params["delete_id"]
    try:
        drive_service.files().delete(fileId=del_id).execute()
        if del_id in st.session_state.my_uploads:
            st.session_state.my_uploads.remove(del_id)
        st.success("Memory deleted!")
    except Exception as e:
        st.error(f"Delete failed: {e}")
    del st.query_params["delete_id"]
    st.rerun()

st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Share your favorite moments and browse live memories below.")

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
    
    # --- HANDLE ZIP ARCHIVE CREATION ---
    if "zip_ids" in params and drive_service:
        zip_ids = params["zip_ids"].split(",")
        with st.spinner(f"Packaging {len(zip_ids)} memories into a ZIP folder..."):
            try:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fid in zip_ids:
                        f_meta = drive_service.files().get(fileId=fid, fields="name").execute()
                        req = drive_service.files().get_media(fileId=fid)
                        file_bytes = io.BytesIO()
                        downloader = MediaIoBaseDownload(file_bytes, req)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()
                        file_name = f_meta.get("name", f"wedding_photo_{fid}.jpg")
                        zf.writestr(file_name, file_bytes.getvalue())
                
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
                        del st.query_params["zip_ids"]
                        st.rerun()
                st.markdown("---")
            except Exception as e:
                st.error(f"Error creating ZIP: {e}")

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
                html_items = []
                for file in files:
                    fid = file.get('id')
                    mime = file.get('mimeType', '')
                    thumb = file.get('thumbnailLink', '').replace('=s220', '=s400')
                    view_url = file.get('webViewLink', '#')
                    is_mine = fid in st.session_state.my_uploads
                    
                    if 'image' in mime and thumb:
                        media_content = f'<img src="{thumb}" alt="Photo" />'
                    else:
                        media_content = '<div class="video-label">▶ Video</div>'
                    
                    delete_html = f'<button class="delete-btn" title="Delete Photo" onclick="deleteItem(\'{fid}\')">✕</button>' if is_mine else ''
                        
                    html_items.append(f'''
                    <div class="grid-card">
                        <input type="checkbox" class="select-check" data-id="{fid}" onclick="updateCount()" />
                        {delete_html}
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
                    
                    /* FIXED 3-COLUMN MOBILE GRID */
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
                    
                    /* TOP-LEFT OVERLAY: CHECKBOX */
                    .select-check {{
                        position: absolute;
                        top: 6px;
                        left: 6px;
                        z-index: 10;
                        width: 22px;
                        height: 22px;
                        accent-color: #1a73e8;
                        cursor: pointer;
                    }}

                    /* TOP-RIGHT OVERLAY: DELETE BUTTON */
                    .delete-btn {{
                        position: absolute;
                        top: 6px;
                        right: 6px;
                        z-index: 10;
                        width: 22px;
                        height: 22px;
                        border-radius: 50%;
                        background: rgba(0, 0, 0, 0.65);
                        border: 1px solid rgba(255, 255, 255, 0.8);
                        color: white;
                        font-size: 11px;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    }}
                    
                    /* ACTION BAR */
                    .action-bar {{
                        margin-top: 12px;
                        padding: 10px 14px;
                        background: #1e1e1e;
                        border-radius: 8px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        color: #fff;
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
                        function updateCount() {{
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
                                window.parent.location.search = '?zip_ids=' + ids.join(',');
                            }}
                        }}

                        function deleteItem(fid) {{
                            if (confirm("Delete this photo from the album?")) {{
                                window.parent.location.search = '?delete_id=' + fid;
                            }}
                        }}
                    </script>
                </body>
                </html>
                '''
                
                grid_rows = (len(files) + 2) // 3
                calculated_height = (grid_rows * 130) + 80
                st.components.v1.html(gallery_html, height=calculated_height, scrolling=False)

        except Exception as e:
            st.error(f"Google Drive Error: {e}")

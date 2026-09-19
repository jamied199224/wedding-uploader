import io
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

if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []

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
    """Create a fresh Google Drive service with clean SSL socket settings."""
    creds = get_credentials()
    http = httplib2.Http(timeout=120)
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build('drive', 'v3', http=authorized_http)

@st.cache_resource
def get_google_services():
    try:
        return create_drive_service()
    except Exception as e:
        st.error(f"Failed to authenticate with Google: {e}")
        return None

def upload_file_to_drive(file_bytes, file_name, mime_type, folder_id):
    """Upload large files reliably using requests to avoid httplib2 redirect issues."""
    creds = get_credentials()
    headers = {"Authorization": f"Bearer {creds.token}"}
    
    # Step 1: Initiate resumable upload session
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
        
    # Step 2: Upload file bytes to session URL
    put_headers = {
        "Content-Type": mime_type,
        "Content-Length": str(len(file_bytes))
    }
    upload_res = requests.put(upload_url, headers=put_headers, data=file_bytes, timeout=300)
    
    if upload_res.status_code in [200, 201]:
        return upload_res.json().get('id')
    else:
        raise Exception(f"Upload failed ({upload_res.status_code}): {upload_res.text}")

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
                
                for index, uploaded_file in enumerate(uploaded_files):
                    file_raw = uploaded_file.getvalue()
                    file_size_mb = len(file_raw) / (1024 * 1024)
                    
                    status_text.text(f"Uploading {index + 1} of {total_files}: {uploaded_file.name} ({file_size_mb:.1f} MB)...")
                    uploaded_successfully = False
                    last_err = None
                    
                    file_title = f"{guest_name or 'Guest'}_{uploaded_file.name}"
                    mime_type = uploaded_file.type or 'application/octet-stream'

                    for attempt in range(3):
                        try:
                            file_id = upload_file_to_drive(
                                file_raw, 
                                file_title, 
                                mime_type, 
                                TARGET_FOLDER_ID
                            )
                            if file_id and file_id not in st.session_state.my_uploads:
                                st.session_state.my_uploads.append(file_id)
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
    
    # --- HANDLE ZIP ARCHIVE CREATION ---
    if "zip_ids" in params and drive_service:
        zip_ids = params["zip_ids"].split(",")
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
                                    raise Exception(f"HTTP {res.status_code}: {res.text[:100]}")
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
                    active_service = drive_service if attempt == 0 else create_drive_service()
                    results = active_service.files().list(
                        q=query,
                        pageSize=100,
                        fields="files(id, name, webViewLink, webContentLink, thumbnailLink, mimeType)",
                        orderBy="createdTime desc"
                    ).execute()
                    break
                except (ssl.SSLError, socket.error, Exception) as net_err:
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
                    thumb_small = file.get('thumbnailLink', '').replace('=s220', '=s400')
                    full_image = file.get('thumbnailLink', '').replace('=s220', '=s1600')
                    preview_url = f"https://drive.google.com/file/d/{fid}/preview"
                    is_mine = fid in st.session_state.my_uploads
                    is_video = 'video' in mime or 'mp4' in mime or 'mov' in mime
                    
                    if not is_video and thumb_small:
                        media_content = f'<img src="{thumb_small}" alt="Photo" />'
                    else:
                        media_content = '<div class="video-label">▶ Video</div>'
                    
                    delete_html = f'<button class="delete-btn" title="Delete Photo" onclick="deleteItem(event, \'{fid}\')">✕</button>' if is_mine else ''
                        
                    html_items.append(f'''
                    <div class="grid-card">
                        <input type="checkbox" class="select-check" data-id="{fid}" onclick="updateCount(event)" />
                        {delete_html}
                        <div class="card-link" onclick="openModal('{full_image}', '{preview_url}', {'true' if is_video else 'false'})">
                            {media_content}
                        </div>
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
                        cursor: pointer;
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
                        function openModal(fullImg, previewUrl, isVideo) {{
                            const parentWin = window.parent;
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

                            // Close on backdrop click
                            overlay.onclick = function(e) {{
                                if (e.target === overlay) {{
                                    parentWin.closeWeddingModal();
                                }}
                            }};

                            overlay.innerHTML = '';

                            // Create distinct Close Button element directly in parent window
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
                                window.parent.location.search = '?zip_ids=' + ids.join(',');
                            }}
                        }}

                        function deleteItem(e, fid) {{
                            if (e) e.stopPropagation();
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


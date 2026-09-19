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
    uploaded_files = st.file_uploader(
        "Choose photos or videos", 
        type=["jpg", "jpeg", "png", "mp4", "mov"],
        accept_multiple_files=True
    )
    guest_name = st.text_input("Your Name (Optional)")

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
                            mimetype=uploaded_file.type,
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
            
            # Fetch files with a retry wrapper for network/SSL glitches
            results = None
            for attempt in range(3):
                try:
                    results = drive_service.files().list(
                        q=query,
                        pageSize=50,
                        fields="files(id, name, webViewLink, thumbnailLink, mimeType)",
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
                selected_files = []

                # Clean 3-column photo grid layout
                cols = st.columns(3)
                for idx, file in enumerate(files):
                    col = cols[idx % 3]
                    with col:
                        try:
                            file_id = file.get('id')
                            file_name = file.get('name', 'Memory')
                            mime_type = file.get('mimeType', '')
                            thumb_link = file.get('thumbnailLink')
                            web_link = file.get('webViewLink', '#')
                            is_mine = file_id in st.session_state.my_uploads
                            
                            # Clean image or video preview container
                            if 'image' in mime_type and thumb_link:
                                st.image(thumb_link.replace('=s220', '=s800'), use_container_width=True)
                            elif 'video' in mime_type:
                                st.markdown("🎥 **[Video File Preview]**")
                            else:
                                st.markdown("📁 *Media File*")
                            
                            # Minimalist action bar underneath each photo (Checkbox select, View link, Delete if mine)
                            action_cols = st.columns([0.5, 0.3, 0.2])
                            with action_cols[0]:
                                if st.checkbox("Select", key=f"sel_{file_id}", label_visibility="collapsed"):
                                    selected_files.append((file_name, web_link))
                            with action_cols[1]:
                                st.markdown(f"[📥 Open]({web_link})")
                            with action_cols[2]:
                                if is_mine:
                                    if st.button("❌", key=f"del_{file_id}", help="Delete your upload"):
                                        deleted = False
                                        for del_attempt in range(3):
                                            try:
                                                drive_service.files().delete(fileId=file_id).execute()
                                                deleted = True
                                                break
                                            except Exception:
                                                if del_attempt == 2:
                                                    raise
                                        if deleted:
                                            st.session_state.my_uploads.remove(file_id)
                                            st.rerun()
                            
                            # Subtle spacing between rows
                            st.write("")
                            
                        except Exception:
                            pass

                # --- FLOATING BATCH DOWNLOAD PANEL ---
                if selected_files:
                    st.markdown("---")
                    st.subheader(f"📦 Selected for Download ({len(selected_files)} items)")
                    st.write("Click any link below to open and save your selected memories:")
                    
                    dl_cols = st.columns(min(len(selected_files), 3))
                    for s_idx, (fname, flink) in enumerate(selected_files):
                        d_col = dl_cols[s_idx % len(dl_cols)]
                        with d_col:
                            st.markdown(f"- [{fname[:25]}]({flink})", unsafe_allow_html=True)
                    st.markdown("---")

        except Exception as e:
            st.warning("Connection hiccup communicating with Google Drive. Please refresh the page.")

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# Page configuration
st.set_page_config(
    page_title="Jamie & Millie's Wedding Media Uploader",
    page_icon="💍",
    layout="centered"
)

# --- TARGET GOOGLE DRIVE FOLDER ID ---
TARGET_FOLDER_ID = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl"

# --- INITIALIZE SESSION STATE FOR DEVICE TRACKING ---
if 'my_uploads' not in st.session_state:
    st.session_state.my_uploads = []  # Tracks file IDs uploaded by *this specific device session*

# --- PERSONAL TOUCH: PHOTO & TITLE ---
# st.image("millie_and_jamie.jpg", width=300) 
st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Please share your favorite photos and videos from our special day with us, and manage your uploads.")

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

# --- TAB LAYOUT: UPLOAD VS. GALLERY ---
tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Guest Gallery & Management"])

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
                failed_files = []
                
                for index, uploaded_file in enumerate(uploaded_files):
                    status_text.text(f"Uploading file {index + 1} of {total_files}: {uploaded_file.name}...")
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
                            fields='id, webViewLink'
                        ).execute()
                        
                        file_id = file.get('id')
                        # Track this file ID so *this device* can manage/delete it later
                        if file_id not in st.session_state.my_uploads:
                            st.session_state.my_uploads.append(file_id)
                            
                        success_count += 1
                    except Exception as e:
                        failed_files.append((uploaded_file.name, str(e)))
                    
                    progress_bar.progress((index + 1) / total_files)
                
                status_text.empty()
                progress_bar.empty()
                
                if success_count > 0:
                    st.success(f"Thank you! Successfully uploaded {success_count} of {total_files} memories.")
                
                if failed_files:
                    st.warning(f"Failed to upload {len(failed_files)} file(s). Try a smaller batch.")
                    for fname, err in failed_files:
                        st.text(f"- {fname}: {err}")

with tab2:
    st.header("Wedding Gallery & Device Management")
    st.write("Browse memories shared by everyone. You can multi-select files *you* uploaded from this device to delete or view.")
    
    if drive_service:
        try:
            query = f"'{TARGET_FOLDER_ID}' in parents and trashed=false"
            results = drive_service.files().list(
                q=query,
                pageSize=20,
                fields="files(id, name, webViewLink, mimeType)",
                orderBy="createdTime desc"
            ).execute()
            files = results.get('files', [])

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                # Multi-select action container for device owner's files
                my_device_files = [f for f in files if f['id'] in st.session_state.my_uploads]
                
                if my_device_files:
                    st.subheader("🗑️ Manage Your Device Uploads")
                    st.write("Select from the files you've uploaded during this session:")
                    
                    selected_to_delete = []
                    for file in my_device_files:
                        if st.checkbox(f"Select to delete: {file.get('name')}", key=f"del_{file['id']}"):
                            selected_to_delete.append(file['id'])
                    
                    if selected_to_delete:
                        if st.button("Delete Selected From Drive"):
                            with st.spinner("Removing selected files..."):
                                for file_id in selected_to_delete:
                                    try:
                                        drive_service.files().delete(fileId=file_id).execute()
                                        st.session_state.my_uploads.remove(file_id)
                                    except Exception as e:
                                        st.error(f"Could not delete file: {e}")
                                st.success("Selected files removed successfully!")
                                st.rerun()
                    st.divider()

                st.subheader("All Guest Memories")
                cols = st.columns(2)
                for idx, file in enumerate(files):
                    col = cols[idx % 2]
                    with col:
                        file_name = file.get('name', 'Memory')
                        mime_type = file.get('mimeType', '')
                        is_mine = file['id'] in st.session_state.my_uploads
                        
                        st.write(f"**{file_name}** {'*(Your Upload)*' if is_mine else ''}")
                        
                        if 'image' in mime_type:
                            st.info("📷 Photo File")
                        elif 'video' in mime_type:
                            st.info("🎥 Video File")
                        
                        st.markdown(f"[Open / Download]({file.get('webViewLink')})", unsafe_allow_html=True)
                        st.divider()
        except Exception as e:
            st.error(f"Could not load gallery: {e}")

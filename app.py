import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

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

# --- PERSONAL TOUCH: PHOTO & TITLE ---
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
tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Interactive Gallery"])

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
            results = drive_service.files().list(
                q=query,
                pageSize=30,
                fields="files(id, name, webViewLink, thumbnailLink, mimeType)",
                orderBy="createdTime desc"
            ).execute()
            files = results.get('files', [])

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                st.write("Browse through memories. Click **Download** to save an item, or click **❌ Delete** on your own uploads to remove them.")
                
                # Grid layout (3 columns)
                cols = st.columns(3)
                for idx, file in enumerate(files):
                    col = cols[idx % 3]
                    with col:
                        # Isolate each card in a try-except so a single bad file never crashes the app
                        try:
                            file_id = file.get('id')
                            file_name = file.get('name', 'Memory')
                            mime_type = file.get('mimeType', '')
                            thumb_link = file.get('thumbnailLink')
                            is_mine = file_id in st.session_state.my_uploads
                            
                            # Card header with optional delete button for user's own uploads
                            header_cols = st.columns([0.8, 0.2])
                            with header_cols[0]:
                                display_name = file_name[:18] + "..." if len(file_name) > 18 else file_name
                                st.markdown(f"**{display_name}**")
                            with header_cols[1]:
                                if is_mine:
                                    if st.button("❌", key=f"del_{file_id}", help="Delete your upload"):
                                        try:
                                            drive_service.files().delete(fileId=file_id).execute()
                                            st.session_state.my_uploads.remove(file_id)
                                            st.success("Deleted!")
                                            st.rerun()
                                        except Exception as del_err:
                                            st.error(f"Error: {del_err}")
                            
                            # Thumbnail or placeholder rendering
                            if 'image' in mime_type and thumb_link:
                                st.image(thumb_link.replace('=s220', '=s400'), use_container_width=True)
                            elif 'image' in mime_type:
                                st.info("📷 Image File")
                            else:
                                st.info("🎥 Video File")
                            
                            # Direct download link
                            web_link = file.get('webViewLink', '#')
                            st.markdown(f"[📥 Download / Open]({web_link})", unsafe_allow_html=True)
                            st.divider()
                            
                        except Exception as card_error:
                            st.warning(f"Could not load item: {card_error}")

        except Exception as e:
            st.error(f"Could not load gallery: {e}")

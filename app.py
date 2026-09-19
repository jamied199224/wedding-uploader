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

# --- PERSONAL TOUCH: PHOTO & TITLE ---
# st.image("millie_and_jamie.jpg", width=300) 
st.title("💍 Jamie & Millie's Wedding Album")
st.write("Welcome! Please share your favorite photos and videos from our special day with us, and browse memories uploaded so far.")

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
tab1, tab2 = st.tabs(["📤 Upload Memories", "🖼️ Guest Gallery"])

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
                            'name': f"{guest_name or 'Guest'}_{uploaded_file.name}"
                        }
                        media = MediaIoBaseUpload(
                            io.BytesIO(uploaded_file.getvalue()),
                            mimetype=uploaded_file.type,
                            resumable=True
                        )

                        # Secure sandboxed Drive upload
                        file = drive_service.files().create(
                            body=file_metadata,
                            media_body=media,
                            fields='id, webViewLink, thumbnailLink'
                        ).execute()
                        
                        success_count += 1
                    except Exception as e:
                        # Catch connection drops or bad files individually so it doesn't crash the app
                        failed_files.append((uploaded_file.name, str(e)))
                    
                    progress_bar.progress((index + 1) / total_files)
                
                status_text.empty()
                progress_bar.empty()
                
                if success_count > 0:
                    st.success(f"Thank you! Successfully uploaded {success_count} of {total_files} memories.")
                
                if failed_files:
                    st.warning(f"Failed to upload {len(failed_files)} file(s):")
                    for fname, err in failed_files:
                        st.text(f"- {fname}: {err}")

with tab2:
    st.header("Wedding Gallery")
    st.write("Browse through memories shared by family and friends:")
    
    if drive_service:
        try:
            results = drive_service.files().list(
                pageSize=50,
                fields="files(id, name, webViewLink, thumbnailLink, mimeType)",
                orderBy="createdTime desc"
            ).execute()
            files = results.get('files', [])

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                cols = st.columns(2)
                for idx, file in enumerate(files):
                    col = cols[idx % 2]
                    with col:
                        st.write(f"**{file.get('name', 'Memory')}**")
                        mime_type = file.get('mimeType', '')
                        if 'image' in mime_type:
                            thumb_link = file.get('thumbnailLink')
                            if thumb_link:
                                st.image(thumb_link.replace('=s220', '=s600'), use_container_width=True)
                        elif 'video' in mime_type:
                            st.info("🎥 Video File")
                        
                        st.markdown(f"[View / Download]({file.get('webViewLink')})", unsafe_allow_html=True)
                        st.divider()
        except Exception as e:
            st.error(f"Could not load gallery: {e}")

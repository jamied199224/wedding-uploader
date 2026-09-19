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
# If you have an image URL or local file for you and Millie, display it here:
# st.image("path_to_your_picture.jpg", width=300) 
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
    uploaded_file = st.file_uploader(
        "Choose a file", 
        type=["jpg", "jpeg", "png", "mp4", "mov"]
    )
    guest_name = st.text_input("Your Name")

    if uploaded_file is not None:
        if st.button("Submit to Wedding Album"):
            if not drive_service:
                st.error("Google services are not initialized.")
            else:
                with st.spinner("Safely uploading your memory..."):
                    try:
                        file_metadata = {
                            'name': f"{guest_name or 'Guest'}_{uploaded_file.name}"
                        }
                        media = MediaIoBaseUpload(
                            io.BytesIO(uploaded_file.getvalue()),
                            mimetype=uploaded_file.type,
                            resumable=True
                        )

                        file = drive_service.files().create(
                            body=file_metadata,
                            media_body=media,
                            fields='id, webViewLink, thumbnailLink'
                        ).execute()

                        st.success("Thank you! Your memory has been added successfully.")
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

with tab2:
    st.header("Wedding Gallery")
    st.write("Browse through memories shared by family and friends:")
    
    if drive_service:
        try:
            # Query files created by the app (sandboxed securely)
            results = drive_service.files().list(
                pageSize=50,
                fields="files(id, name, webViewLink, thumbnailLink, mimeType)",
                orderBy="createdTime desc"
            ).execute()
            files = results.get('files', [])

            if not files:
                st.info("No photos or videos uploaded yet. Be the first!")
            else:
                # Display files in a clean grid
                cols = st.columns(2)
                for idx, file in enumerate(files):
                    col = cols[idx % 2]
                    with col:
                        st.write(f"**{file.get('name', 'Memory')}**")
                        if 'image' in file.get('mimeType', ''):
                            # Show thumbnail if available
                            thumb_link = file.get('thumbnailLink')
                            if thumb_link:
                                st.image(thumb_link.replace('=s220', '=s600'), use_container_width=True)
                        elif 'video' in file.get('mimeType', ''):
                            st.info("🎥 Video File")
                        
                        # Provide direct view/download links
                        st.markdown(f"[View / Download]({file.get('webViewLink')})", unsafe_allow_html=True)
                        st.divider()
        except Exception as e:
            st.error(f"Could not load gallery: {e}")

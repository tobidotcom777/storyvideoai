import streamlit as st
import requests
import boto3
import os
from moviepy.editor import ImageSequenceClip, AudioFileClip, CompositeVideoClip, TextClip
from moviepy.video.tools.subtitles import SubtitlesClip

# Access credentials from secrets.toml (Managed by Streamlit)
openai_api_key = st.secrets["OPENAI_API_KEY"]
aws_access_key_id = st.secrets["AWS_ACCESS_KEY_ID"]
aws_secret_access_key = st.secrets["AWS_SECRET_ACCESS_KEY"]
aws_region = st.secrets["AWS_REGION"]
aws_s3_bucket_name = st.secrets["AWS_S3_BUCKET_NAME"]

# Set up AWS S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=aws_region
)

# OpenAI API URLs
IMAGE_API_URL = "https://api.openai.com/v1/images/generations"
TTS_API_URL = "https://api.openai.com/v1/audio/speech"
HEADERS = {"Authorization": f"Bearer {openai_api_key}"}

AVAILABLE_VOICES = ["Alloy", "Echo", "Fable", "Onyx", "Nova", "Shimmer"]

# Helper function to upload to S3
def upload_to_s3(filename):
    try:
        s3_key = f"generated_files/{filename}"
        s3_client.upload_file(filename, aws_s3_bucket_name, s3_key)
        file_url = f"https://{aws_s3_bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"
        st.write(f"Uploaded {filename} to S3: {file_url}")
        return file_url
    except Exception as e:
        st.error(f"Failed to upload {filename} to S3: {e}")
        return None

# Delete files from S3
def delete_from_s3(s3_key):
    try:
        s3_client.delete_object(Bucket=aws_s3_bucket_name, Key=s3_key)
        st.write(f"Deleted {s3_key} from S3")
    except Exception as e:
        st.error(f"Failed to delete {s3_key} from S3: {e}")

# Function to generate images from a prompt
def generate_image_from_prompt(prompt):
    if not prompt.strip():
        st.error("Prompt cannot be empty.")
        return None
    try:
        data = {
            "model": "dall-e-3",  # Specify the model
            "prompt": prompt,
            "n": 1,  # DALL-E 3 only supports n=1
            "size": "1024x1024",  # Can be 1024x1024, 1792x1024, or 1024x1792
            "response_format": "url"  # The format of the returned image
        }
        response = requests.post(IMAGE_API_URL, headers=HEADERS, json=data)
        
        # Log the API response for debugging
        st.write(f"API Response: {response.text}")  # Log the response to the Streamlit interface
        
        response.raise_for_status()  # Raise an HTTPError for bad responses
        
        # Parse the image URL from the response
        image_data = response.json().get('data', [])
        if not image_data:
            st.error("No image URLs were returned by the API.")
            return None
        
        return image_data[0]['url']
    
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error occurred: {http_err}")
        return None
    except Exception as e:
        st.error(f"Error generating image: {str(e)}")
        return None

# Generate voice overlay using OpenAI's TTS API
def generate_voice_overlay(text, voice="Alloy", speed=1):
    if not text.strip():
        st.error("Text for voiceover cannot be empty.")
        return None
    try:
        data = {
            "model": "tts-1",
            "input": text,
            "voice": voice.lower(),
            "speed": speed,
            "response_format": "mp3"
        }
        response = requests.post(TTS_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        voiceover_filename = "voiceover.mp3"
        with open(voiceover_filename, "wb") as f:
            f.write(response.content)
        return voiceover_filename
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error occurred: {http_err}")
        return None
    except Exception as e:
        st.error(f"Error generating voiceover: {str(e)}")
        return None

# Function to create subtitles based on text and duration
def create_subtitles(text, duration):
    lines = text.split("\n")
    if not lines:
        st.error("Subtitle text cannot be empty.")
        return []
    
    subtitles = []
    per_line_duration = duration / len(lines)
    start_time = 0

    for line in lines:
        if not line.strip():
            continue
        end_time = start_time + per_line_duration
        subtitles.append(((start_time, end_time), line.strip()))
        start_time = end_time

    return subtitles

# Generate video from images, audio, and subtitles
def compile_video(images, voiceover, subtitles, font_style, output_file="output_video.mp4"):
    total_duration = 60  # Limit video to 60 seconds
    image_duration = total_duration / len(images)
    
    clips = []
    for idx, image_url in enumerate(images):
        img_data = requests.get(image_url).content
        img_file = f'image_{idx}.jpg'
        with open(img_file, 'wb') as handler:
            handler.write(img_data)
        clips.append(img_file)
    
    clip = ImageSequenceClip(clips, durations=[image_duration] * len(images))
    audio_clip = AudioFileClip(voiceover)
    clip = clip.set_audio(audio_clip)
    
    # Subtitle generation
    generator = lambda txt: TextClip(txt, font=font_style, fontsize=24, color='white')
    subtitle_clip = SubtitlesClip(subtitles, generator)
    final_video = CompositeVideoClip([clip, subtitle_clip.set_pos(('center', 'bottom'))])
    
    # Write video file
    final_video.write_videofile(output_file, codec='libx264', audio_codec='aac')
    return output_file

# Clean up story segments to remove numbering
def clean_story_segments(story_segments):
    cleaned_segments = []
    for segment in story_segments:
        cleaned_segment = segment.strip()
        if not cleaned_segment[0].isdigit() or '.' not in cleaned_segment[:3]:
            cleaned_segments.append(cleaned_segment)
    return cleaned_segments

# Streamlit app interface
st.title("Story-Driven Video Generator")

user_prompt = st.text_area("Enter a short story or theme for the video:", "Spooky Haunted Graveyard in Texas")
voice_choice = st.selectbox("Choose a voice for the narration:", AVAILABLE_VOICES)
font_choice = st.selectbox("Choose a font style for subtitles:", ["Arial-Bold", "Courier", "Helvetica", "Times-Roman", "Verdana"])

if st.button("Generate Video"):
    st.info("Generating story video... Please be patient, this may take a few minutes.")
    
    # Validate user input
    if not user_prompt.strip():
        st.error("Please enter a valid story or theme.")
    else:
        # Placeholder for optimized prompt and cleaned story segments
        story_segments = [f"{i+1}. {user_prompt}" for i in range(5)]  # Generate fake 5 segments for testing
        story_segments = clean_story_segments(story_segments)
        
        # Generate images
        images = []
        for segment in story_segments:
            img_url = generate_image_from_prompt(segment)
            if img_url:
                images.append(img_url)
        
        if len(images) == 0:
            st.error("No images were generated. Please check the prompt or try again.")
        else:
            # Generate voiceover
            voiceover_file = generate_voice_overlay("\n".join(story_segments), voice=voice_choice)
            
            if voiceover_file:
                # Create subtitles
                subtitles = create_subtitles("\n".join(story_segments), 60)
                
                # Compile video
                video_file = compile_video(images, voiceover_file, subtitles, font_choice)
                
                # Upload final video to S3
                s3_video_url = upload_to_s3(video_file)
                
                # Display the video in the app
                st.video(video_file)
                
                # Download button for the video
                with open(video_file, "rb") as f:
                    st.download_button("Download Video", data=f, file_name="output_video.mp4")
                
                # Clean up S3 space
                delete_from_s3(f"generated_files/{voiceover_file}")
                for idx, _ in enumerate(images):
                    delete_from_s3(f"generated_files/image_{idx}.jpg")

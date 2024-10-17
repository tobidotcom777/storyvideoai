import streamlit as st
import requests
import boto3
import os
from moviepy.editor import ImageSequenceClip, AudioFileClip, CompositeVideoClip, TextClip
from moviepy.video.tools.subtitles import SubtitlesClip

# Access credentials from secrets.toml
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
    s3_key = f"generated_files/{filename}"
    try:
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
    data = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "url"
    }
    response = requests.post(IMAGE_API_URL, headers=HEADERS, json=data)
    if response.status_code == 200:
        return response.json()['data'][0]['url']
    else:
        st.error(f"Error generating image: {response.text}")
        return None

# Generate voice overlay using OpenAI's TTS API
def generate_voice_overlay(text, voice="Alloy", speed=1):
    data = {
        "model": "tts-1",
        "input": text,
        "voice": voice.lower(),
        "speed": speed,
        "response_format": "mp3"
    }
    response = requests.post(TTS_API_URL, headers=HEADERS, json=data)
    if response.status_code == 200:
        voiceover_filename = "voiceover.mp3"
        with open(voiceover_filename, "wb") as f:
            f.write(response.content)
        return voiceover_filename
    else:
        st.error(f"Error generating voiceover: {response.text}")
        return None

# Function to create subtitles based on text and duration
def create_subtitles(text, duration):
    lines = text.split("\n")
    subtitles = []
    per_line_duration = duration / len(lines)
    start_time = 0

    for line in lines:
        end_time = start_time + per_line_duration
        subtitles.append(((start_time, end_time), line))
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

user_prompt = st.text_area("Enter a short story or theme for the video:", "Spooky Hunted Graveyard in Texas")
voice_choice = st.selectbox("Choose a voice for the narration:", AVAILABLE_VOICES)
font_choice = st.selectbox("Choose a font style for subtitles:", ["Arial-Bold", "Courier", "Helvetica", "Times-Roman", "Verdana"])

if st.button("Generate Video"):
    st.info("Generating story video... Please be patient, this may take a few minutes.")
    
    # Placeholder for optimized prompt and cleaned story segments
    optimized_prompt = user_prompt  # For now, just use raw user input
    story_segments = [f"{i+1}. {optimized_prompt}" for i in range(5)]  # Fake 5 segments for now
    story_segments = clean_story_segments(story_segments)
    
    # Generate images
    images = []
    for segment in story_segments:
        img_url = generate_image_from_prompt(segment)
        if img_url:
            images.append(img_url)
    
    # Generate voiceover
    voiceover_file = generate_voice_overlay("\n".join(story_segments[:5]), voice=voice_choice)
    
    # Create subtitles
    subtitles = create_subtitles("\n".join(story_segments), 60)
    
    # Compile video
    if images and voiceover_file:
        video_file = compile_video(images, voiceover_file, subtitles, font_choice)
        
        # Upload final video to S3
        s3_video_url = upload_to_s3(video_file)
        
        # Display the video in the app
        st.video(video_file)
        
        # Download button for the video
        with open(video_file, "rb") as f:
            st.download_button("Download Video", data=f, file_name="final_video.mp4", mime="video/mp4")
        
        # Clean up intermediate files
        delete_from_s3(f"generated_files/{voiceover_file}")
        for img_file in images:
            os.remove(img_file)
        os.remove(video_file)

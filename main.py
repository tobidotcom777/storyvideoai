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
CHAT_API_URL = "https://api.openai.com/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {openai_api_key}"}

AVAILABLE_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

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

# Function to enhance the user prompt
def enhance_prompt(prompt):
    try:
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": f"Enhance the following prompt for a story video: {prompt}"}
            ]
        }
        response = requests.post(CHAT_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()
        enhanced_prompt = response.json()['choices'][0]['message']['content']
        return enhanced_prompt
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error enhancing prompt: {http_err}")
        return prompt
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return prompt

# Function to generate a consistent style prompt based on the enhanced prompt
def generate_style_prompt(enhanced_prompt):
    try:
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": f"Generate a comma-separated list of style and setting descriptions for images based on the following enhanced prompt: {enhanced_prompt}"}
            ]
        }
        response = requests.post(CHAT_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()
        style_prompt = response.json()['choices'][0]['message']['content']
        return style_prompt
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error generating style prompt: {http_err}")
        return ""
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return ""

# Function to generate story segments from the enhanced prompt
def generate_story_segments(enhanced_prompt):
    try:
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": f"Create a short story with a maximum of 5 segments from the following prompt: {enhanced_prompt}"}
            ]
        }
        response = requests.post(CHAT_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()
        story = response.json()['choices'][0]['message']['content']
        return story.split("\n")[:5]
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error generating story: {http_err}")
        return []
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return []

# Function to create a consistent image prompt
def create_image_prompt(segment, style_prompt):
    negative_prompt = "Make sure there is no text in the image."
    return f"{style_prompt}, {segment.strip()}, {negative_prompt}"

# Function to generate images from a prompt
def generate_image_from_prompt(prompt):
    if not prompt.strip():
        st.error("Prompt cannot be empty.")
        return None
    try:
        data = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "url"
        }

        st.write(f"Sending prompt to OpenAI API: {prompt}")

        response = requests.post(IMAGE_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()
        
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
def generate_voice_overlay(text, voice="alloy", speed=1):
    if not text.strip():
        st.error("Text for voiceover cannot be empty.")
        return None
    
    try:
        data = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": "mp3"
        }

        st.write(f"Sending data to OpenAI TTS API: {data}")

        response = requests.post(TTS_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()
        
        voiceover_filename = "voiceover.mp3"
        with open(voiceover_filename, "wb") as f:
            f.write(response.content)
        return upload_to_s3(voiceover_filename)
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
def compile_video(images, voiceover_url, subtitles, font_style, output_file="output_video.mp4"):
    total_duration = 60  # Limit video to 60 seconds
    image_duration = total_duration / len(images) if images else 0
    clips = []

    for idx, image_url in enumerate(images):
        img_clip = ImageSequenceClip([image_url], fps=24).set_duration(image_duration)
        clips.append(img_clip)

    audio_clip = AudioFileClip(voiceover_url).set_duration(total_duration)
    video = CompositeVideoClip(clips).set_duration(total_duration).set_audio(audio_clip)

    # Create subtitles
    generator = lambda txt: TextClip(txt, font=font_style, fontsize=24, color='white')
    subtitle_clip = SubtitlesClip(subtitles, generator)
    
    # Combine video and subtitles
    final_video = CompositeVideoClip([video, subtitle_clip])
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac")

    return upload_to_s3(output_file)  # Upload final video to S3

# Main app interface
st.title("Story-Driven Video Generator")

user_prompt = st.text_area("Enter a short story or theme for the video:", "Spooky Haunted Graveyard in Texas")
voice_choice = st.selectbox("Choose a voice for the narration:", AVAILABLE_VOICES)
font_choice = st.selectbox("Choose a font style for subtitles:", ["Arial-Bold", "Courier", "Helvetica", "Times-Roman", "Verdana"])

if st.button("Generate Video"):
    st.info("Generating story video... Please be patient, this may take a few minutes.")
    
    if not user_prompt.strip():
        st.error("Please enter a valid story or theme.")
    else:
        with st.spinner("Enhancing your prompt..."):
            enhanced_prompt = enhance_prompt(user_prompt)
            st.write(f"Enhanced Prompt: {enhanced_prompt}")

        with st.spinner("Generating style prompt..."):
            style_prompt = generate_style_prompt(enhanced_prompt)
            st.write(f"Style Prompt: {style_prompt}")

        with st.spinner("Generating story segments..."):
            story_segments = generate_story_segments(enhanced_prompt)
            story_segments = [segment for segment in story_segments if segment]
            story_segments = story_segments[:5]
            st.write("Generated Story Segments:")
            for segment in story_segments:
                st.write(segment)
        
        images = []
        for segment in story_segments:
            with st.spinner(f"Generating image for: {segment}"):
                img_url = generate_image_from_prompt(create_image_prompt(segment, style_prompt))
                if img_url:
                    images.append(img_url)
                else:
                    st.error("No images were generated. Please check the prompt or try again.")
                    break
        
        if len(images) > 0:
            with st.spinner("Generating voiceover..."):
                voiceover_url = generate_voice_overlay("\n".join(story_segments), voice=voice_choice)

                if voiceover_url:
                    subtitles = create_subtitles("\n".join(story_segments), 60)
                    
                    with st.spinner("Compiling video..."):
                        video_url = compile_video(images, voiceover_url, subtitles, font_choice)
                        
                        if video_url:
                            st.video(video_url)
                            
                            with open(video_url.split('/')[-1], "rb") as f:
                                st.download_button("Download Video", data=f, file_name="output_video.mp4")
                        else:
                            st.error("Video compilation failed. Please try again.")

import streamlit as st
import requests
import boto3
import os
from moviepy.editor import ImageSequenceClip, AudioFileClip, CompositeVideoClip, TextClip

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

AVAILABLE_VOICES = ["Alloy", "Echo", "Fable", "Onyx", "Nova", "Shimmer"]
AVAILABLE_FONTS = ["Arial-Bold", "Courier", "Helvetica", "Times-Roman", "Verdana"]

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
            "model": "gpt-4o-mini",  # Use gpt-4o-mini for prompt enhancement
            "messages": [
                {"role": "user", "content": f"Enhance the following prompt for a story video: {prompt}"}
            ]
        }
        response = requests.post(CHAT_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        enhanced_prompt = response.json()['choices'][0]['message']['content']
        return enhanced_prompt
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error enhancing prompt: {http_err}")
        return prompt  # Fallback to the original prompt in case of error

# Function to generate story segments from the enhanced prompt
def generate_story_segments(enhanced_prompt):
    try:
        data = {
            "model": "gpt-4o-mini",  # Use gpt-4o-mini for story generation
            "messages": [
                {"role": "user", "content": f"Create a short story with a maximum of 5 segments from the following prompt: {enhanced_prompt}"}
            ]
        }
        response = requests.post(CHAT_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        story = response.json()['choices'][0]['message']['content']
        return story.split("\n")[:5]  # Limit to first 5 segments
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error generating story: {http_err}")
        return []  # Return an empty list in case of error

# Function to create a consistent image prompt
def create_image_prompt(segment):
    negative_prompt = "Make sure there is no text in the image."
    return f"{segment.strip()} {negative_prompt}"

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
            "size": "1024x1024",  # Specify size
            "response_format": "url"  # The format of the returned image
        }

        # Log the prompt being sent for debugging
        st.write(f"Sending prompt to OpenAI API: {prompt}")

        response = requests.post(IMAGE_API_URL, headers=HEADERS, json=data)

        # Check for HTTP errors
        response.raise_for_status()  # Raise an HTTPError for bad responses

        # Extract image URL from response
        return response.json()["data"][0]["url"]
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error generating image: {http_err}")
        return None  # Return None if there's an error

# Function to generate voice overlay
def generate_voice_overlay(input_text, voice="onyx"):
    if not input_text.strip():
        st.error("Input text cannot be empty.")
        return None
    try:
        data = {
            "model": "tts-1",
            "input": input_text,
            "voice": voice,
            "response_format": "mp3"
        }
        response = requests.post(TTS_API_URL, headers=HEADERS, json=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        audio_file_path = "voiceover.mp3"
        with open(audio_file_path, 'wb') as audio_file:
            audio_file.write(response.content)
        return audio_file_path
    except requests.exceptions.HTTPError as http_err:
        st.error(f"Error generating voiceover: {http_err}")
        return None  # Return None if there's an error

# Function to compile the final video with images, audio, and subtitles
def compile_video(images, voiceover, font):
    clips = []
    total_duration = len(images) * 3  # 3 seconds per image

    for img_url in images:
        img_clip = ImageSequenceClip([img_url], fps=24).set_duration(3)
        clips.append(img_clip)

    audio_clip = AudioFileClip(voiceover).set_duration(total_duration)
    video = CompositeVideoClip(clips).set_duration(total_duration).set_audio(audio_clip)

    # Generate subtitles using the selected font
    subtitles = [(i * 3, (i + 1) * 3, segment) for i, segment in enumerate(story_segments)]
    subtitle_clips = [TextClip(txt, fontsize=24, color='white', font=font).set_position('bottom').set_duration(3).set_start(start) for start, end, txt in subtitles]
    
    # Composite the video with subtitles
    for subtitle in subtitle_clips:
        video = CompositeVideoClip([video, subtitle])
    
    output_file = "output_video.mp4"
    video.write_videofile(output_file, codec="libx264", audio_codec="aac")

    return output_file

# Main app interface
st.title("Story-Driven Video Generator")

user_prompt = st.text_area("Enter a short story or theme for the video:", "Spooky Haunted Graveyard in Texas")
voice_choice = st.selectbox("Choose a voice for the narration:", AVAILABLE_VOICES)
font_choice = st.selectbox("Choose a font style for the subtitles:", AVAILABLE_FONTS)

if st.button("Generate Video"):
    st.info("Generating story video... Please be patient, this may take a few minutes.")
    
    # Validate user input
    if not user_prompt.strip():
        st.error("Please enter a valid story or theme.")
    else:
        # Enhance the user prompt
        with st.spinner("Enhancing your prompt..."):
            enhanced_prompt = enhance_prompt(user_prompt)
            st.write(f"Enhanced Prompt: {enhanced_prompt}")

        # Generate story segments from the enhanced prompt
        with st.spinner("Generating story segments..."):
            story_segments = generate_story_segments(enhanced_prompt)
            story_segments = [segment for segment in story_segments if segment]  # Remove any empty segments
            story_segments = story_segments[:5]  # Limit to first 5 segments
            st.write("Generated Story Segments:")
            for segment in story_segments:
                st.write(segment)
        
        # Generate images (limited to 5 images)
        images = []
        for segment in story_segments:
            with st.spinner(f"Generating image for: {segment}"):
                img_url = generate_image_from_prompt(create_image_prompt(segment))
                if img_url:
                    images.append(img_url)
                else:
                    st.error("No images were generated. Please check the prompt or try again.")
                    break  # Exit loop if any image fails to generate
        
        if len(images) > 0:  # Proceed only if at least one image was generated
            # Generate voiceover
            with st.spinner("Generating voiceover..."):
                voiceover_file = generate_voice_overlay("\n".join(story_segments), voice=voice_choice)

                if voiceover_file:
                    # Compile video
                    with st.spinner("Compiling video..."):
                        video_file = compile_video(images, voiceover_file, font_choice)
                        if video_file:
                            st.success("Video successfully created!")
                            st.video(video_file)
                            st.download_button("Download Video", video_file)
                            # Upload the final video to S3
                            upload_to_s3(video_file)

# Clear temporary files if needed (optional)
# os.remove("voiceover.mp3")
# for img in images:
#     os.remove(img)  # Clean up any image files if downloaded


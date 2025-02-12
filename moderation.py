import os
import time
import cv2
import urllib.request
import json
from dotenv import load_dotenv


def load_credentials():

    if os.path.exists(".env"):
        load_dotenv()
        return (
            os.getenv("ACCESS_KEY"),
            os.getenv("SECRET_KEY"),
            os.getenv("AWS_REGION")
        )
    return None, None, None


def check_filetype(filename):

    file_basename = os.path.basename(filename)
    extension = file_basename.split(".")[-1].lower()

    if extension in ["jpg", "png", "tiff", "svg", "jpeg"]:
        filetype = "image"
    elif extension in ["mp4", "avi", "mkv", "mov"]:
        filetype = "vidéo"
    else:
        filetype = None

    print(f"[INFO] : Le fichier {file_basename} est de type : {filetype}")
    return filetype


def extract_frame_video(video_path, frame_id=0):

    video = cv2.VideoCapture(video_path)
    video.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ret, image = video.read()
    return image if ret else None


def moderate_image_bytes(img_bytes, rekognition):

    r = rekognition.detect_moderation_labels(Image={'Bytes': img_bytes})
    return [label["Name"] for label in r["ModerationLabels"]]


def get_text_from_speech(filename, transcribe_client, s3_client, job_name, bucket_name):

    object_key = f"temp/transcriptions/{job_name}.mp4"

    s3_client.upload_file(filename, bucket_name, object_key)

    media_uri = f"s3://{bucket_name}/{object_key}"

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': media_uri},
        MediaFormat='mp4',
        LanguageCode='fr-FR'
    )
    
    while True:
        response = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]
        if status in ["COMPLETED", "FAILED"]:
            break
        time.sleep(5)

    if status == "COMPLETED":
        # Récupérer l'URL du JSON de transcription
        url = response["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read())
        return data["results"]["transcripts"][0]["transcript"]

    return None


def process_media(media_file, rekognition, transcribe, comprehend, s3, bucket_name):
    e = media_file.lower()

    # CAS IMAGE
    if e.endswith(('png', 'jpg', 'jpeg')):
        with open(media_file, 'rb') as image:
            img_bytes = image.read()
        if not img_bytes:
            return None  # Erreur lecture du fichier

        # Vérification modération
        r = rekognition.detect_moderation_labels(Image={'Bytes': img_bytes})
        if r['ModerationLabels']:
            # Fichier sensible
            return {
                "moderation_labels": [lbl["Name"] for lbl in r['ModerationLabels']]
            }

        # Détection labels / visages / célébrités
        d_labels = rekognition.detect_labels(Image={'Bytes': img_bytes}, MaxLabels=10)
        d_faces = rekognition.detect_faces(Image={'Bytes': img_bytes}, Attributes=['ALL'])
        d_celeb = rekognition.recognize_celebrities(Image={'Bytes': img_bytes})

        # Construction d'une liste de hashtags
        h = set("#" + lbl['Name'] for lbl in d_labels['Labels'])
        for f in d_faces.get('FaceDetails', []):
            if f.get('Emotions'):
                h.add("#" + f['Emotions'][0]['Type'])
        h.update("#" + c['Name'] for c in d_celeb.get('CelebrityFaces', []))

        return {
            "subtitles": None,
            "hashtags": list(h)
        }

    # CAS VIDÉO
    elif e.endswith(('mp4', 'avi', 'mov', 'mkv')):
        # Extraction de la première frame pour la modération
        frame = extract_frame_video(media_file, 0)
        if frame is None:
            return None

        import cv2
        ret, img_encoded = cv2.imencode('.jpg', frame)
        if not ret:
            return None
        img_bytes = img_encoded.tobytes()

        # Modération sur la frame
        r = rekognition.detect_moderation_labels(Image={'Bytes': img_bytes})
        if r['ModerationLabels']:
            return {
                "moderation_labels": [lbl["Name"] for lbl in r['ModerationLabels']]
            }

        # Détection labels / visages / célébrités
        d_labels = rekognition.detect_labels(Image={'Bytes': img_bytes}, MaxLabels=10)
        d_faces = rekognition.detect_faces(Image={'Bytes': img_bytes}, Attributes=['ALL'])
        d_celeb = rekognition.recognize_celebrities(Image={'Bytes': img_bytes})

        # Construction d'une liste de hashtags (issus de l'analyse d'image)
        h = set("#" + lbl['Name'] for lbl in d_labels['Labels'])
        for f in d_faces.get('FaceDetails', []):
            if f.get('Emotions'):
                h.add("#" + f['Emotions'][0]['Type'])
        h.update("#" + c['Name'] for c in d_celeb.get('CelebrityFaces', []))

        # Transcription audio via Amazon Transcribe
        job_name = f"transcription-job-{int(time.time())}"
        subtitles = get_text_from_speech(
            filename=media_file,
            transcribe_client=transcribe,
            s3_client=s3,
            job_name=job_name,
            bucket_name=bucket_name
        )
        if not subtitles:
            return None  # Échec transcription ?

        # Extraction de mots-clés avec Comprehend => hashtags
        cr = comprehend.detect_key_phrases(Text=subtitles, LanguageCode='fr')
        keywords = ["#" + p['Text'] for p in cr.get('KeyPhrases', [])]

        # Fusion des hashtags issus de l'image et de la transcription
        final_hashtags = list(h.union(keywords))

        return {
            "subtitles": subtitles,
            "hashtags": final_hashtags
        }
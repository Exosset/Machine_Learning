import streamlit as st
import boto3
import os
import tempfile
import moderation


st.set_page_config(page_title="Content Inspector", layout="wide")

st.title("📸 Content Inspector")
st.subheader("Vérifiez et modérez vos contenus en un clic !")
st.markdown("---")

# -------------------------------------------------------------------
# Paramétrage via la barre latérale
# -------------------------------------------------------------------
st.sidebar.title("⚙️ Paramètres")
st.sidebar.subheader("🔑 Identifiants AWS")

# Variables de session
if "access_key" not in st.session_state:
    st.session_state.access_key = ""
if "secret_key" not in st.session_state:
    st.session_state.secret_key = ""
if "region" not in st.session_state:
    st.session_state.region = "us-east-1"

# Bouton : charger depuis .env
if st.sidebar.button("📂 Charger depuis `.env`"):
    ak, sk, rg = moderation.load_credentials()
    if ak and sk:
        st.session_state.access_key = ak
        st.session_state.secret_key = sk
        st.session_state.region = rg or st.session_state.region
        st.sidebar.success("✅ Identifiants importés avec succès.")
    else:
        st.sidebar.error("❌ Erreur : `.env` introuvable ou incomplet.")

# Champs de saisie : Access Key / Secret Key / Region
st.session_state.access_key = st.sidebar.text_input(
    "Access Key",
    type="password",
    value=st.session_state.access_key
)
st.session_state.secret_key = st.sidebar.text_input(
    "Secret Key",
    type="password",
    value=st.session_state.secret_key
)
st.session_state.region = st.sidebar.text_input(
    "AWS Region",
    value="eu-west-2"  # Par défaut, si besoin
)


bucket_name = st.sidebar.text_input("📦 Nom du bucket S3", value="tomsupdevinci")

# Bouton : valider la config
if st.sidebar.button("✅ Valider"):
    if st.session_state.access_key and st.session_state.secret_key and bucket_name:
        st.sidebar.success("✅ Paramètres validés.")
    else:
        st.sidebar.error("❌ Veuillez remplir tous les champs.")

st.markdown("---")

# -------------------------------------------------------------------
# Zone d'upload de fichier
# -------------------------------------------------------------------
st.header("📤 Transférer un fichier")
uploaded_file = st.file_uploader(
    "Choisissez une image ou une vidéo",
    type=["jpg", "png", "jpeg", "mp4", "avi", "mkv"]
)

if uploaded_file:
    file_bytes = uploaded_file.read()
    file_type = moderation.check_filetype(uploaded_file.name)
    st.success(f"✅ Fichier importé : `{uploaded_file.name}`")

    # Configuration des clients Boto3 si identifiants présents
    if st.session_state.access_key and st.session_state.secret_key:
        rekognition_client = boto3.client(
            "rekognition",
            region_name=st.session_state.region,
            aws_access_key_id=st.session_state.access_key,
            aws_secret_access_key=st.session_state.secret_key
        )
        transcribe_client = boto3.client(
            "transcribe",
            region_name=st.session_state.region,
            aws_access_key_id=st.session_state.access_key,
            aws_secret_access_key=st.session_state.secret_key
        )
        comprehend_client = boto3.client(
            "comprehend",
            region_name=st.session_state.region,
            aws_access_key_id=st.session_state.access_key,
            aws_secret_access_key=st.session_state.secret_key
        )
        s3_client = boto3.client(
            "s3",
            region_name=st.session_state.region,
            aws_access_key_id=st.session_state.access_key,
            aws_secret_access_key=st.session_state.secret_key
        )
    else:
        rekognition_client = transcribe_client = comprehend_client = s3_client = None
        st.warning("⚠️ Les services AWS ne sont pas configurés.")

    # Traitement et analyse
    with st.spinner("Analyse en cours..."):
        extension = os.path.splitext(uploaded_file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(file_bytes)
            temp_path = tmp_file.name

        if rekognition_client and transcribe_client and comprehend_client and s3_client:
            result = moderation.process_media(
                media_file=temp_path,
                rekognition=rekognition_client,
                transcribe=transcribe_client,
                comprehend=comprehend_client,
                s3=s3_client,
                bucket_name=bucket_name
            )
            # Nettoyage du fichier temporaire
            if os.path.exists(temp_path):
                os.remove(temp_path)



            # Interprétation du résultat
            if result is None:
                st.error("🚨 Erreur pendant la lecture ou la transcription.")
            elif "moderation_labels" in result:
                st.markdown(
                    """
                    <div style="background-color: #FFDDDD; padding: 10px; border-radius: 8px; border-left: 5px solid red;">
                        <h4 style="color: red; margin-bottom: 5px;">🚨 Contenu inapproprié détecté</h4>
                        <p style="color: black; margin: 0;">⛔ Cette publication a été bloquée</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if result["moderation_labels"]:
                    st.markdown("### 🔎 Thèmes sensibles détectés :")
                    for theme in result["moderation_labels"]:
                        st.markdown(f"- ⚠️ {theme}")
            else:
                # Aperçu (image ou vidéo)
                if file_type == "image":
                    try:
                        st.image(file_bytes, caption="Aperçu de l'image")
                    except Exception as e:  # Capture toutes les exceptions
                        st.error("⚠️ La taille de l'image est trop grande ou un problème est survenu !")

                elif file_type == "vidéo":
                    st.video(file_bytes)


            if result.get("hashtags"):

                hashtags_html = " ".join(
                    f'<span class="hashtag">{tag}</span>' for tag in result["hashtags"]
                )

                st.markdown(
                    f"""
                    <style>
                        .hashtag {{
                            background-color: #E6F7FF; /* Bleu très clair pour le fond */
                            color: #66B3CC; /* Bleu doux pour le texte */
                            padding: 3px 8px; /* Réduire un peu l'espace */
                            border-radius: 12px; /* Coins arrondis */
                            margin: 3px;
                            display: inline-block;
                            font-size: 14px; /* Plus petit */
                            font-weight: normal; /* Enlever le gras */
                        }}
                    </style>
                    {hashtags_html}
                    """,
                    unsafe_allow_html=True,
                )



            # Tout est OK => Affichage
            if result.get("subtitles"):
                with st.expander("📝 Voir la transcription", expanded=True):
                    st.write(result["subtitles"])

        else:
            st.warning("⚠️ Impossible de procéder à l'analyse (AWS non accessible).")
            # Affichage simple sans analyse
            if file_type == "image":
                st.image(file_bytes, caption="Aperçu de l'image (non analysé)")
            elif file_type == "vidéo":
                st.video(file_bytes)
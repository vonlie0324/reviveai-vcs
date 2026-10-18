FROM python:3.12-slim

WORKDIR /app

# Video caption overlays require an installed scalable bold TrueType font.
# Fail the image build rather than discovering missing fonts during production.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "from PIL import Image, ImageDraw, ImageFont; import imageio_ffmpeg; font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 48); image = Image.new('RGB', (640, 120), 'black'); ImageDraw.Draw(image).text((20, 20), 'ReviveAI caption check', font=font, fill='white'); print('Assembly dependencies and scalable caption font verified'); print('FFmpeg executable:', imageio_ffmpeg.get_ffmpeg_exe())"

COPY app ./app

ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

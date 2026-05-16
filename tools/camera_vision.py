"""
camera_vision.py — Webcam capture and vision analysis tool for Nova.

Captures a frame from the default webcam, sends it to the active
AI model (cloud or Ollama vision), and returns the response.
"""

import os
import tempfile
import shutil
from datetime import datetime


def camera_vision(prompt, ai_instance):
    """
    Capture a webcam frame and analyse it using the active AI model.

    Args:
        prompt: What to ask about the image
        ai_instance: The WorkingAI instance (self.ai in nova_assistant_v1)

    Returns:
        str: AI response describing or analysing the image
    """
    try:
        import cv2
    except ImportError:
        return "❌ OpenCV not installed. Run: pip install opencv-python"

    # Capture frame
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return "❌ Camera not available or in use by another application."

    # Let camera warm up — first frame is often dark
    for _ in range(3):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return "❌ Failed to capture frame from camera."

    # Save to temp file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        cv2.imwrite(tmp_path, frame)
        web_dir = "web_images"
        os.makedirs(web_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        web_filename = f"camera_{timestamp}.jpg"
        web_path = os.path.join(web_dir, web_filename)
        shutil.copy2(tmp_path, web_path)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return "❌ Failed to write camera image."

        # Check model supports vision
        model = getattr(ai_instance, "model", "")
        vision_models = [
            "claude", "gpt-4o", "gemini", "llava",
            "llava-phi3", "moondream", "bakllava"
        ]
        is_vision = any(v in model.lower() for v in vision_models)

        if not is_vision:
            return (f"⚠️ Current model '{model}' may not support vision. "
                    f"Switch to Claude, GPT-4o, or a LLaVA Ollama model.")

        # Save a copy to web_images so it renders in the web interface

        web_dir = "web_images"
        os.makedirs(web_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        web_filename = f"camera_{timestamp}.jpg"
        web_path = os.path.join(web_dir, web_filename)
        shutil.copy2(tmp_path, web_path)

        result = ai_instance.generate(prompt, image_path=tmp_path, use_planning=False)
        result = result or "No response from model."

        return f"[IMAGE:{web_filename}]\n\n{result}"

    except Exception as e:
        return f"❌ Camera vision error: {e}"

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
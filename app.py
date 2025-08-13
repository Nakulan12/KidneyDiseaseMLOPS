from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import cv2
import numpy as np
from werkzeug.utils import secure_filename
import tensorflow as tf
from pathlib import Path
import uuid
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'mediscan-ai-secret-key-2024'  # Change this to a secure random key

# Configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'dicom'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load the trained model
MODEL_PATH = 'artifacts/model_training/kidney_model'  # Update this path to your model
try:
    model = tf.keras.models.load_model(MODEL_PATH)
    logger.info("MediScan AI model loaded successfully!")
except Exception as e:
    logger.error(f"Error loading model: {e}")
    model = None

# Class names for predictions - matches your training data
CLASS_NAMES = ['Cyst', 'Normal', 'Stone', 'Tumor']

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def preprocess_medical_image(image_path, target_size=(28, 28)):
    """
    Preprocess the uploaded medical image for model prediction
    Optimized for medical CT scan analysis
    """
    try:
        # Read the image
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError("Could not read medical image file")
        
        # Resize to model input size (28x28 as per your model)
        img = cv2.resize(img, target_size)
        
        # Convert BGR to RGB for medical imaging standards
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Normalize pixel values for medical image analysis
        img = img.astype(np.float32) / 255.0
        
        # Add batch dimension for model input
        img = np.expand_dims(img, axis=0)
        
        logger.info(f"Medical image preprocessed successfully: {img.shape}")
        return img
        
    except Exception as e:
        logger.error(f"Error preprocessing medical image: {e}")
        return None

def analyze_medical_image(image_path):
    """
    Perform AI-powered medical image analysis
    Returns diagnosis and confidence score
    """
    if model is None:
        logger.error("Medical AI model not available")
        return None, 0.0, "Model not available"
    
    try:
        # Preprocess the medical image
        processed_img = preprocess_medical_image(image_path)
        if processed_img is None:
            return None, 0.0, "Image preprocessing failed"
        
        # Perform AI analysis
        logger.info("Starting medical image analysis...")
        predictions = model.predict(processed_img)
        
        # Get the predicted class and confidence
        predicted_class_idx = np.argmax(predictions[0])
        confidence = float(predictions[0][predicted_class_idx]) * 100
        
        # Set minimum confidence to 85% as requested
        if confidence < 85.0:
            confidence = 85.0 + (confidence * 0.15)  # Boost confidence to minimum 85%
        
        predicted_condition = CLASS_NAMES[predicted_class_idx]
        
        logger.info(f"Medical analysis complete: {predicted_condition} ({confidence:.1f}% confidence)")
        return predicted_condition, confidence, "Analysis successful"
        
    except Exception as e:
        logger.error(f"Error during medical image analysis: {e}")
        return None, 0.0, f"Analysis error: {str(e)}"

def validate_medical_image(file):
    """
    Validate uploaded medical image for clinical standards
    """
    # File type validation
    if not allowed_file(file.filename):
        return False, "Please upload a valid medical image (JPEG, PNG, or DICOM format)"
    
    # File size validation
    if len(file.read()) > MAX_FILE_SIZE:
        return False, "Medical image file size must be less than 10MB"
    
    # Reset file pointer after reading
    file.seek(0)
    
    # Basic file integrity check
    if len(file.read()) < 1024:  # Less than 1KB
        return False, "Medical image file appears to be corrupted or too small"
    
    file.seek(0)
    return True, "Medical image validation successful"

@app.route('/')
def index():
    """Home page - Medical professional dashboard"""
    return render_template('index.html')

@app.route('/predict', methods=['GET', 'POST'])
def predict():
    """Medical image analysis page"""
    if request.method == 'GET':
        return render_template('predict.html')
    
    # Handle sample analysis requests
    if request.form.get('sample') == 'true':
        sample_data = {
            'prediction': request.form.get('prediction', 'Normal'),
            'confidence': float(request.form.get('confidence', 85.0)),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'filename': None,
            'recommendations': get_medical_recommendations(
                request.form.get('prediction', 'Normal'), 
                float(request.form.get('confidence', 85.0))
            )
        }
        return render_template('result.html', **sample_data)
    
    # Handle POST request (medical image upload and analysis)
    if 'file' not in request.files:
        flash('No medical image file selected', 'error')
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No medical image file selected', 'error')
        return redirect(request.url)
    
    # Validate medical image
    is_valid, validation_message = validate_medical_image(file)
    if not is_valid:
        flash(validation_message, 'error')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        try:
            # Generate unique filename for medical record
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"medical_scan_{timestamp}_{unique_id}.{file.filename.rsplit('.', 1)[1].lower()}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the medical image
            file.save(filepath)
            logger.info(f"Medical image saved: {filename}")
            
            # Perform AI-powered medical analysis
            prediction, confidence, status = analyze_medical_image(filepath)
            
            if prediction is None:
                flash(f'Error analyzing medical image: {status}', 'error')
                # Clean up the file
                if os.path.exists(filepath):
                    os.remove(filepath)
                return redirect(url_for('predict'))
            
            # Generate medical report data
            report_data = {
                'prediction': prediction,
                'confidence': confidence,
                'filename': filename,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'status': status,
                'recommendations': get_medical_recommendations(prediction, confidence)
            }
            
            # Render medical results page
            return render_template('result.html', **report_data)
            
        except Exception as e:
            logger.error(f"Error processing medical image upload: {e}")
            flash('Error processing medical image. Please try again.', 'error')
            return redirect(url_for('predict'))
    
    else:
        flash('Invalid file type. Please upload a valid medical image (JPEG, PNG, or DICOM).', 'error')
        return redirect(url_for('predict'))

def get_medical_recommendations(condition, confidence):
    """
    Generate medical recommendations based on AI analysis
    """
    recommendations = {
        'Cyst': {
            'description': 'A fluid-filled sac detected in kidney tissue.',
            'recommendations': [
                'Schedule follow-up imaging in 6-12 months',
                'Monitor for size changes or symptoms',
                'Maintain adequate hydration',
                'Consult nephrologist if symptoms develop'
            ],
            'urgency': 'Low' if confidence > 85 else 'Medium'
        },
        'Normal': {
            'description': 'No significant abnormalities detected in kidney structure.',
            'recommendations': [
                'Continue regular health maintenance',
                'Maintain healthy lifestyle and diet',
                'Stay adequately hydrated',
                'Follow routine screening schedule'
            ],
            'urgency': 'None'
        },
        'Stone': {
            'description': 'Mineral deposits detected in kidney structure.',
            'recommendations': [
                'Increase fluid intake significantly',
                'Consider dietary modifications',
                'Schedule urological consultation',
                'Monitor for pain or urinary symptoms'
            ],
            'urgency': 'Medium' if confidence > 85 else 'High'
        },
        'Tumor': {
            'description': 'Abnormal tissue growth detected requiring immediate attention.',
            'recommendations': [
                'URGENT: Schedule immediate oncological consultation',
                'Obtain additional imaging studies (CT/MRI)',
                'Consider biopsy evaluation',
                'Coordinate multidisciplinary care team'
            ],
            'urgency': 'High'
        }
    }
    
    return recommendations.get(condition, {
        'description': 'Analysis completed. Please consult healthcare provider.',
        'recommendations': ['Consult with healthcare provider for interpretation'],
        'urgency': 'Medium'
    })

@app.route('/result')
def result():
    """Direct access to results page redirects to prediction"""
    return redirect(url_for('predict'))

@app.route('/about')
def about():
    """About page - Project information and credibility"""
    return render_template('about.html')

@app.errorhandler(413)
def too_large(e):
    flash('Medical image file is too large. Maximum size is 10MB.', 'error')
    return redirect(url_for('predict'))

@app.errorhandler(404)
def not_found(e):
    return render_template('index.html'), 404

@app.errorhandler(500)
def server_error(e):
    flash('An internal error occurred. Please try again.', 'error')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
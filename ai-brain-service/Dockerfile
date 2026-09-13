# User a lightweight Python image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# COPY your model and the FASTAPI code
COPY gateway_ai_model_v2.joblib .
COPY main.py .

# Expose the port FASTAPI runs on
EXPOSE 8000

# Start the service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]



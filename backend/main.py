from fastapi import FastAPI
from services.aws_service import AWSService

app = FastAPI(
    title="CloudOps AI",
    description="AI-powered Cloud Operations Platform",
    version="0.1.0",
)

aws_service = AWSService()


@app.get("/")
def root():
    return {
        "message": "CloudOps AI is running",
        "version": "0.1.0",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "cloudops-ai",
    }


@app.get("/cloud/aws/status")
def aws_status():
    return aws_service.get_status()
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
@app.get("/cloud/aws/services/{service_name}")
def aws_service_health(service_name: str):
    return aws_service.get_service_health(service_name)

@app.get("/cloud/aws/ec2/summary")
def aws_ec2_summary():
    return aws_service.get_ec2_summary()

@app.get("/cloud/aws/ec2/instances")
def aws_ec2_instances():
    return aws_service.get_ec2_instances()
import os, jwt, json
from dotenv import load_dotenv

load_dotenv()

refresh_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJhZG1pbiIsImV4cCI6MTc1NDA3MjA3OCwidHlwZSI6InJlZnJlc2gifQ.IpU-ccA1cP8mJFhS639Ng94LKyUwr_qn2i7YthCq2dw"
secret_key = os.getenv("SECRET_KEY")
if secret_key is None:
    print("SECRET_KEY env var is missing!")
else:
    try:
        payload = jwt.decode(refresh_token, secret_key, algorithms=["HS256"])
        print(payload)
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        roles: str = payload.get("roles")
        if token_type != "refresh" or username is None:
            raise HTTPException(status_code=401, detail="Invalid token: incorrect type or user")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    print("valid")

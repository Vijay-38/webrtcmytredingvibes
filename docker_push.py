import os, sys, datetime

IMAGE_NAME = "flask-webrtc"
DOCKER_USER = "viraj234"
DOCKER_TOKEN = os.environ.get("DOCKER_TOKEN", "")  # NOSONAR - should use env var in production
TAG = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def run(cmd):
    print(f"> {cmd}")
    if os.system(cmd) != 0:
        print(f"FAILED: {cmd}"); sys.exit(1)

print("=== LOGGING INTO DOCKER HUB ===")
run(f"echo {DOCKER_TOKEN} | docker login -u {DOCKER_USER} --password-stdin")

print("\n=== BUILDING DOCKER IMAGE ===")
run(f"docker build --platform linux/amd64 -t {IMAGE_NAME}:{TAG} -t {IMAGE_NAME}:latest .")

print("\n=== TAGGING FOR DOCKER HUB ===")
run(f"docker tag {IMAGE_NAME}:{TAG} {DOCKER_USER}/{IMAGE_NAME}:{TAG}")
run(f"docker tag {IMAGE_NAME}:latest {DOCKER_USER}/{IMAGE_NAME}:latest")

print("\n=== PUSHING TO DOCKER HUB ===")
run(f"docker push {DOCKER_USER}/{IMAGE_NAME}:{TAG}")
run(f"docker push {DOCKER_USER}/{IMAGE_NAME}:latest")

print("\n=== DONE! ===")
print(f"Pushed: {DOCKER_USER}/{IMAGE_NAME}:{TAG}")
print(f"Pushed: {DOCKER_USER}/{IMAGE_NAME}:latest")

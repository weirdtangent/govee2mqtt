FROM python:3.9-alpine

# Update package lists and upgrade system packages
RUN apt-get update && apt-get upgrade -y

# Upgrade pip and setuptools
RUN pip install --upgrade pip setuptools

# Install dependencies
RUN apk add --no-cache gcc libffi-dev musl-dev

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade -r requirements.txt

RUN pip check

COPY . .

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup -g $GROUP_ID appuser && \
    adduser -u $USER_ID -G appuser --disabled-password --gecos "" appuser

USER appuser

CMD [ "python", "./app.py", "-c", "/config"]

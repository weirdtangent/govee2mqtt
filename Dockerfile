FROM python:3.9-alpine

# Install dependencies
RUN apk add --no-cache gcc libffi-dev musl-dev

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup -G $GROUP_ID appuser && \
    adduser -u $USER_ID -G appuser --disabled-password --gecos "" appuser

USER appuser

CMD [ "python", "./app.py", "-c", "/config"]

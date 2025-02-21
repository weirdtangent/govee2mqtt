FROM python:3.9-alpine

# Install dependencies
RUN apk add --no-cache gcc libffi-dev musl-dev

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup --gid $GROUP_ID appuser && \
    adduser --uid $USER_ID --gid $GROUP_ID --disabled-password --gecos "" appuser

USER appuser

CMD [ "python", "./app.py", "-c", "/config"]

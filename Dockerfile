FROM python:3.14-alpine
LABEL authors="qetesh"
WORKDIR /app
COPY requirements.txt ./
# 抑制 root 用户警告
ENV PIP_ROOT_USER_ACTION=ignore
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
CMD [ "python3","-u","main.py" ]
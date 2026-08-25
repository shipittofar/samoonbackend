# use this doccker file when you don`t have network connection.

#FROM python:3.13-slim
#
#ENV PYTHONDONTWRITEBYTECODE=1
#ENV PYTHONUNBUFFERED=1
#
#WORKDIR /app
#
#COPY requirements.txt .
#COPY docker/django/wheels ./wheels
#
##RUN pip install --upgrade pip
##RUN pip install -r requirements.txt
#
#RUN pip install \
#    --no-index \
#    --find-links=/app/wheels \
#    -r requirements.txt
#
#COPY . .
#
#CMD ["gunicorn", "SmartRestaurant.wsgi:application", "--bind", "0.0.0.0:8000", "--reload"]


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "SmartRestaurant.wsgi:application", "--bind", "0.0.0.0:8000", "--reload"]
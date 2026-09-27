from flask import Blueprint, jsonify

main = Blueprint("main", __name__)


@main.get("/")
def index():
    return jsonify(message="SubTranslate-2 is running")

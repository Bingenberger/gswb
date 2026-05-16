import os
from pathlib import Path


def create_app(test_config=None):
    from flask import Flask

    from .db import init_db
    from .repository import WordRepository
    from .routes import bp
    from .services.handwriting_service import build_handwriting_service
    from .services.json_review_service import JsonReviewService
    from .services.search_service import SearchService

    package_dir = Path(__file__).resolve().parent
    base_dir = package_dir.parent
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
        static_url_path="/static",
    )

    app.config.from_mapping(
        SECRET_KEY="grundschul-woerterbuch-dev",
        DATABASE=str(base_dir / "data" / "grundschul_woerterbuch.sqlite3"),
        IMPORT_DIR=str(base_dir / "data" / "import_words"),
        MEDIA_IMAGE_DIR=str(base_dir / "static" / "images"),
        MEDIA_AUDIO_DIR=str(base_dir / "static" / "audio"),
        HANDWRITING_UPLOAD_DIR=str(base_dir / "static" / "uploads"),
        HANDWRITING_MODE=os.environ.get("HANDWRITING_MODE", "gemini"),
        HANDWRITING_GEMINI_MODEL=os.environ.get("HANDWRITING_GEMINI_MODEL", "gemini-2.5-flash"),
        GEMINI_CREDENTIALS_FILE=os.environ.get("GEMINI_CREDENTIALS_FILE", str(base_dir / "key.json")),
        GEMINI_LOCATION=os.environ.get("GEMINI_LOCATION", "global"),
    )

    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["IMPORT_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["MEDIA_IMAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["MEDIA_AUDIO_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["HANDWRITING_UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    init_db(app.config["DATABASE"])

    repository = WordRepository(app.config["DATABASE"])
    search_service = SearchService(repository)
    handwriting_service = build_handwriting_service(app.config)
    json_review_service = JsonReviewService(app.config["IMPORT_DIR"])

    app.extensions["word_repository"] = repository
    app.extensions["search_service"] = search_service
    app.extensions["handwriting_service"] = handwriting_service
    app.extensions["json_review_service"] = json_review_service

    app.register_blueprint(bp)
    return app

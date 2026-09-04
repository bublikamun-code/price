#!/usr/bin/env python3
"""Нормализация фото бакета photos-series (§16 п.17).

Конвертер уже встроен в пайплайн загрузки (app/tasks/photo_zip.py:
webp, large fit 1200×1200, thumb fit 400×400, quality 82). Этот скрипт —
одноразовая/периодическая пригонка РАНЕЕ загруженных объектов к тому же
стандарту:

  * основное фото > 1200 px по большей стороне → ужать;
  * не-webp → переконвертировать в webp q82;
  * thumb (`X_thumb.webp`) отсутствует или > 400 px → пересоздать из основного.

Идемпотентен: соответствующие объекты пропускаются без перезаписи.
Запуск на ноде (venv с boto3+Pillow, секреты из api/.env):

    ~/pp/venv/bin/python infra/scripts/normalize-photos.py            # сухой прогон (только отчёт)
    ~/pp/venv/bin/python infra/scripts/normalize-photos.py --apply    # применить изменения
"""
import argparse
import io
import sys
from pathlib import Path

import boto3
from PIL import Image

LARGE_SIZE = (1200, 1200)
THUMB_SIZE = (400, 400)
WEBP_QUALITY = 82
BUCKET = "photos-series"


def load_credentials() -> tuple[str, str, str]:
    env = Path.home() / "pp/app/api/.env"
    vals = {}
    for line in env.read_text().splitlines():
        for k in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_ENDPOINT"):
            if line.startswith(k + "="):
                vals[k] = line.strip().split("=", 1)[1]
    return vals["S3_ENDPOINT"], vals["S3_ACCESS_KEY"], vals["S3_SECRET_KEY"]


def to_webp(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="применить изменения (иначе сухой прогон)")
    args = parser.parse_args()

    endpoint, ak, sk = load_credentials()
    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=ak, aws_secret_access_key=sk)

    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        keys.extend(o["Key"] for o in page.get("Contents", []))

    main_keys = [k for k in keys if not k.endswith("_thumb.webp")]
    thumb_keys = {k for k in keys if k.endswith("_thumb.webp")}

    resized = converted = thumbs_created = errors = skipped = 0
    for key in main_keys:
        try:
            raw = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            with Image.open(io.BytesIO(raw)) as img:
                fmt = (img.format or "").lower()
                large, changed = img.convert("RGB"), False
                if large.width > LARGE_SIZE[0] or large.height > LARGE_SIZE[1]:
                    large = large.copy()
                    large.thumbnail(LARGE_SIZE)
                    changed = True
                if fmt != "webp":
                    changed = True
                thumb = None
                thumb_key = key[: -len(".webp")] + "_thumb.webp" if key.endswith(".webp") else key + "_thumb.webp"
                if thumb_key not in thumb_keys:
                    thumb = large.copy()
                    thumb.thumbnail(THUMB_SIZE)
                if not changed and thumb is None:
                    skipped += 1
                    continue
                if args.apply:
                    if changed:
                        s3.put_object(Bucket=BUCKET, Key=key, Body=to_webp(large), ContentType="image/webp")
                    if thumb is not None:
                        s3.put_object(Bucket=BUCKET, Key=thumb_key, Body=to_webp(thumb), ContentType="image/webp")
                resized += 1 if changed else 0
                converted += 1 if fmt != "webp" else 0
                thumbs_created += 1 if thumb is not None else 0
        except Exception as exc:  # noqa: BLE001 — отчёт по каждому битому объекту
            errors += 1
            print(f"ERROR {key}: {exc}", file=sys.stderr)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] всего основных: {len(main_keys)}, без изменений: {skipped}, "
          f"пережато/переконвертировано: {resized} (из них не-webp: {converted}), "
          f"thumb создано: {thumbs_created}, ошибок: {errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

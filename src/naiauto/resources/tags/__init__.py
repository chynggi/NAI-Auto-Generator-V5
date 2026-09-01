"""NAI Auto Generator V5 태그 데이터 패키지.

NAIA2.0과 동일한 HuggingFace 저장소에서 태그 데이터를 가져온다:

    https://huggingface.co/baqu2213/PoemForSmallFThings

데이터 종류:
  - taglist/*.json    — 태그 분류 (의상/표정/포즈/장소/사물/메타)
  - tag_index/*.json  — 태그 번역/정규화/축 규칙
  - tag_rating.json   — 태그별 Danbooru rating 분포
  - tag_exclusive_pairs.json — 같이 쓰면 안 되는 태그쌍
  - tag_cooccurrence.json    — 자주 함께 쓰이는 태그
  - tag_bucket_dates.json   — 태그 버킷별 날짜 정보
  - danbooru_tags_post_count.csv — (기존) 태그-게시물수 DB
  - danbooru_aliases.csv    — (기존) Danbooru alias DB
"""

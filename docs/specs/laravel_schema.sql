-- Prototype MySQL schema in Laravel/Eloquent conventions.
--
-- PROVISIONAL. The client has not yet answered whether we own the schema and
-- they adapt, whether we must match an existing one, or whether Eloquent
-- conventions are required at all (recorded as blocked in CLAUDE.md). This
-- exists to make that conversation concrete rather than to pre-empt it: it
-- follows Eloquent conventions throughout so it is the version they are most
-- likely to accept unchanged, and every deviation is commented.
--
-- Conventions applied: snake_case plural tables, `id` BIGINT UNSIGNED
-- AUTO_INCREMENT, `created_at`/`updated_at` nullable timestamps, foreign keys
-- named <singular>_id, pivot tables named alphabetically.
--
-- Deliberate deviation: every table also carries the pipeline's own stable
-- string key (course_id, document_id, ...) as a UNIQUE column. Eloquent gets
-- its integer id; the pipeline keeps an identity that survives a reload, so a
-- re-import cannot silently repoint a citation at a different row.

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- Reference data
-- --------------------------------------------------------------------------

CREATE TABLE sources (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_key        VARCHAR(64)     NOT NULL,   -- pipeline id, e.g. 'AICTE'
    name              VARCHAR(255)    NOT NULL,
    authority_type    VARCHAR(128)    NULL,
    tier              CHAR(1)         NOT NULL,   -- A-F, per the client's Source Directory
    coverage          VARCHAR(64)     NULL,
    official_url      VARCHAR(512)    NULL,
    status            VARCHAR(32)     NULL,       -- verified | reachable | blocked | unverified
    created_at        TIMESTAMP       NULL,
    updated_at        TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY sources_source_key_unique (source_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE institutions (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    institution_key   VARCHAR(64)     NOT NULL,
    canonical_name    VARCHAR(512)    NOT NULL,
    aishe_code        VARCHAR(32)     NULL,
    nirf_id           VARCHAR(32)     NULL,
    institution_type  VARCHAR(64)     NULL,
    ownership_type    VARCHAR(64)     NULL,
    city              VARCHAR(128)    NULL,
    state             VARCHAR(128)    NULL,
    official_url      VARCHAR(512)    NULL,
    created_at        TIMESTAMP       NULL,
    updated_at        TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY institutions_institution_key_unique (institution_key),
    KEY institutions_state_index (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE courses (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_key            VARCHAR(128)    NOT NULL,  -- e.g. 'mechanical_engineering'
    standard_course_name  VARCHAR(255)    NOT NULL,
    field_of_study        VARCHAR(128)    NULL,
    qualification_level   VARCHAR(64)     NULL,
    created_at            TIMESTAMP       NULL,
    updated_at            TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY courses_course_key_unique (course_key),
    KEY courses_field_of_study_index (field_of_study)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A course may sit under more than one taxonomy field (four specialisations
-- are cross-listed), so this is many-to-many rather than a column on courses.
CREATE TABLE course_field_of_study (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id     BIGINT UNSIGNED NOT NULL,
    field_name    VARCHAR(128)    NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY course_field_unique (course_id, field_name),
    CONSTRAINT course_field_course_fk FOREIGN KEY (course_id)
        REFERENCES courses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE course_aliases (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id     BIGINT UNSIGNED NOT NULL,
    alias         VARCHAR(255)    NOT NULL,
    PRIMARY KEY (id),
    KEY course_aliases_course_id_index (course_id),
    CONSTRAINT course_aliases_course_fk FOREIGN KEY (course_id)
        REFERENCES courses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Evidence layer (the client's Document store + Source registry)
-- --------------------------------------------------------------------------

CREATE TABLE documents (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    document_key      VARCHAR(64)     NOT NULL,   -- DOC-<hash>
    source_id         BIGINT UNSIGNED NOT NULL,
    document_url      VARCHAR(1024)   NOT NULL,
    document_title    VARCHAR(1024)   NULL,
    file_hash         VARCHAR(128)    NULL,       -- change detection
    content_type      VARCHAR(128)    NULL,
    publication_date  DATE            NULL,
    academic_year     VARCHAR(16)     NULL,
    retrieved_at      TIMESTAMP       NULL,
    created_at        TIMESTAMP       NULL,
    updated_at        TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY documents_document_key_unique (document_key),
    KEY documents_source_id_index (source_id),
    CONSTRAINT documents_source_fk FOREIGN KEY (source_id) REFERENCES sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Content layer
-- --------------------------------------------------------------------------

-- One row per (course, segment): ALWAYS 14 per course, including the ones with
-- nothing behind them. A missing row and a row saying no_source_found are very
-- different claims, and the API must be able to tell a consumer which it is.
CREATE TABLE course_segments (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id      BIGINT UNSIGNED NOT NULL,
    segment        VARCHAR(64)     NOT NULL,   -- one of the 14 canonical segments
    provenance     ENUM('sourced','partially_generated','generated','no_source_found')
                                   NOT NULL DEFAULT 'no_source_found',
    review_required TINYINT(1)     NOT NULL DEFAULT 1,
    publishable    TINYINT(1)      NOT NULL DEFAULT 0,
    reviewed_by    VARCHAR(128)    NULL,
    reviewed_at    TIMESTAMP       NULL,
    generator_model VARCHAR(64)    NULL,       -- set only when generated
    generated_at   TIMESTAMP       NULL,
    created_at     TIMESTAMP       NULL,
    updated_at     TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY course_segments_unique (course_id, segment),
    KEY course_segments_provenance_index (provenance),
    CONSTRAINT course_segments_course_fk FOREIGN KEY (course_id)
        REFERENCES courses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Which sources were checked and produced nothing. This is what makes a
-- generated segment auditable: it asserts the gap was real, not unexamined.
CREATE TABLE course_segment_attempted_sources (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_segment_id  BIGINT UNSIGNED NOT NULL,
    source_id          BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY segment_attempted_unique (course_segment_id, source_id),
    CONSTRAINT attempted_segment_fk FOREIGN KEY (course_segment_id)
        REFERENCES course_segments (id) ON DELETE CASCADE,
    CONSTRAINT attempted_source_fk FOREIGN KEY (source_id) REFERENCES sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The atomic field values. Kept as one row per field rather than a JSON blob
-- per segment so a citation can attach to a FIELD, which is what Hard
-- Constraint 2 requires and what a per-segment blob cannot express.
CREATE TABLE segment_fields (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_segment_id  BIGINT UNSIGNED NOT NULL,
    field_key          VARCHAR(128)    NOT NULL,  -- e.g. 'core_subjects'
    field_id           VARCHAR(8)      NULL,      -- e.g. 'F042'
    value_text         TEXT            NULL,
    value_json         JSON            NULL,      -- list-valued fields
    is_generated       TINYINT(1)      NOT NULL DEFAULT 0,
    created_at         TIMESTAMP       NULL,
    updated_at         TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY segment_fields_unique (course_segment_id, field_key),
    KEY segment_fields_field_id_index (field_id),
    CONSTRAINT segment_fields_segment_fk FOREIGN KEY (course_segment_id)
        REFERENCES course_segments (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One row per (field, evidencing document). A field with is_generated = 1 has
-- NO row here, by construction -- that is the database-level expression of
-- "generated content cannot carry a citation".
CREATE TABLE source_refs (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    segment_field_id  BIGINT UNSIGNED NOT NULL,
    document_id       BIGINT UNSIGNED NOT NULL,
    quoted_evidence   TEXT            NOT NULL,
    page_number       VARCHAR(16)     NULL,
    verification_status ENUM('pending','ai_checked','human_verified','rejected')
                                      NOT NULL DEFAULT 'pending',
    reviewed_by       VARCHAR(128)    NULL,
    created_at        TIMESTAMP       NULL,
    updated_at        TIMESTAMP       NULL,
    PRIMARY KEY (id),
    KEY source_refs_field_index (segment_field_id),
    KEY source_refs_document_index (document_id),
    CONSTRAINT source_refs_field_fk FOREIGN KEY (segment_field_id)
        REFERENCES segment_fields (id) ON DELETE CASCADE,
    CONSTRAINT source_refs_document_fk FOREIGN KEY (document_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Institution-linked facts
-- --------------------------------------------------------------------------

CREATE TABLE rankings (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    institution_id    BIGINT UNSIGNED NOT NULL,
    ranking_body      VARCHAR(64)     NOT NULL,
    ranking_category  VARCHAR(64)     NOT NULL,
    ranking_year      VARCHAR(16)     NOT NULL,
    rank              INT             NULL,
    rank_band         VARCHAR(32)     NULL,
    ranking_score     DECIMAL(6,2)    NULL,
    created_at        TIMESTAMP       NULL,
    updated_at        TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY rankings_unique (institution_id, ranking_body, ranking_category, ranking_year),
    CONSTRAINT rankings_institution_fk FOREIGN KEY (institution_id)
        REFERENCES institutions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE institution_course_offerings (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    institution_id      BIGINT UNSIGNED NOT NULL,
    course_id           BIGINT UNSIGNED NOT NULL,
    official_course_url VARCHAR(1024)   NULL,
    intake              INT             NULL,
    academic_year       VARCHAR(16)     NULL,
    confidence          DECIMAL(3,2)    NOT NULL DEFAULT 0.00,
    created_at          TIMESTAMP       NULL,
    updated_at          TIMESTAMP       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY offering_unique (institution_id, course_id, academic_year),
    CONSTRAINT offering_institution_fk FOREIGN KEY (institution_id)
        REFERENCES institutions (id) ON DELETE CASCADE,
    CONSTRAINT offering_course_fk FOREIGN KEY (course_id)
        REFERENCES courses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

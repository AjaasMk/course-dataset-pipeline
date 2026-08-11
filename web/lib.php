<?php
/**
 * Reads the pipeline's output folders directly.
 *
 * No database: the MySQL schema is still provisional (see
 * docs/specs/laravel_schema.sql) and the client has not confirmed schema
 * ownership, so this prototype renders straight from the JSON the pipeline
 * already writes. Swapping in Eloquent later replaces this file alone.
 */

const DATA_DIR      = __DIR__ . '/../data';
const GENERATED_DIR = DATA_DIR . '/generated';
const INDEX_FILE    = DATA_DIR . '/web/courses.json';

function load_index(): array
{
    if (!is_readable(INDEX_FILE)) {
        return ['segment_order' => [], 'courses' => []];
    }
    return json_decode(file_get_contents(INDEX_FILE), true) ?: ['segment_order' => [], 'courses' => []];
}

function find_course(string $key): ?array
{
    foreach (load_index()['courses'] as $course) {
        if ($course['course_key'] === $key) {
            return $course;
        }
    }
    return null;
}

/** Generated records are one file per (course, segment). */
function generated_filename(string $courseKey, string $segment): string
{
    $slug = str_replace([' ', '&'], ['_', 'and'], $segment);
    return GENERATED_DIR . "/{$courseKey}__{$slug}.json";
}

function load_generated(string $courseKey, string $segment): ?array
{
    $path = generated_filename($courseKey, $segment);
    if (!is_readable($path)) {
        return null;
    }
    return json_decode(file_get_contents($path), true) ?: null;
}

/**
 * One segment's state for a course.
 *
 * provenance is 'generated' | 'sourced' | 'no_source_found'. The distinction
 * matters to the admin view and must never reach the public one.
 */
function segment_state(array $course, string $segment): array
{
    $record = load_generated($course['course_key'], $segment);
    if ($record !== null) {
        return [
            'provenance'        => 'generated',
            'fields'            => $record['fields'] ?? [],
            'generator_model'   => $record['generator_model'] ?? null,
            'generated_at'      => $record['generated_at'] ?? null,
            'sources_attempted' => $record['sources_attempted'] ?? [],
            'review_required'   => $record['review_required'] ?? true,
            'publishable'       => $record['publishable'] ?? false,
            'sources'           => [],
        ];
    }

    $sources = $course['segments'][$segment] ?? [];
    return [
        // A sourced segment has documents but no extracted field values yet:
        // extraction has not been run at scale, so this reports the real state
        // rather than implying content exists.
        'provenance'        => $sources ? 'sourced' : 'no_source_found',
        'fields'            => [],
        'generator_model'   => null,
        'generated_at'      => null,
        'sources_attempted' => [],
        'review_required'   => true,
        'publishable'       => false,
        'sources'           => $sources,
    ];
}

function coverage(array $index): array
{
    $counts = ['sourced' => 0, 'generated' => 0, 'no_source_found' => 0];
    foreach ($index['courses'] as $course) {
        foreach ($index['segment_order'] as $segment) {
            $counts[segment_state($course, $segment)['provenance']]++;
        }
    }
    return $counts;
}

/** Field keys are snake_case internally; the page shows them as prose. */
function humanise(string $key): string
{
    return ucfirst(str_replace('_', ' ', $key));
}

function render_value($value): string
{
    if (is_array($value)) {
        $items = array_map(fn($v) => '<li>' . htmlspecialchars((string) $v) . '</li>', $value);
        return '<ul>' . implode('', $items) . '</ul>';
    }
    return '<p>' . nl2br(htmlspecialchars((string) $value)) . '</p>';
}

function is_admin(): bool
{
    return isset($_GET['admin']) && $_GET['admin'] === '1';
}

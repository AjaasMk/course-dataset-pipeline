<?php
require __DIR__ . '/lib.php';

$index    = load_index();
$courses  = $index['courses'];
$segments = $index['segment_order'];
$totals   = coverage($index);
$cells    = count($courses) * max(count($segments), 1);
$admin    = is_admin();
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Course Library<?= $admin ? ' — Admin' : '' ?></title>
  <link rel="stylesheet" href="style.css">
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <span>Career information for students in Grades 8–12 and their parents</span>
    <span><?= $admin ? 'Admin view' : 'Student view' ?></span>
  </div>
</div>

<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="index.php"><span class="brand-mark">C</span> Career Portal</a>
    <div>
      <a class="btn <?= $admin ? '' : 'active' ?>" href="index.php">Student view</a>
      <a class="btn <?= $admin ? 'active' : '' ?>" href="index.php?admin=1">Admin view</a>
    </div>
  </div>
</header>

<section class="hero">
  <div class="hero-card">
    <span class="eyebrow">Pilot</span>
    <span class="eyebrow"><?= count($courses) ?> courses</span>
    <span class="eyebrow"><?= count($segments) ?> segments each</span>
    <h1>Course Library</h1>
    <p>
      Each course carries the same fourteen segments. A segment is either backed by an
      official source document, generated where no source could be found, or recorded
      as having nothing behind it — never silently omitted.
    </p>
  </div>
</section>

<div class="page">

  <?php if ($admin): ?>
    <div class="content-section">
      <h2>Coverage</h2>
      <p class="sub"><?= $cells ?> cells across <?= count($courses) ?> courses × <?= count($segments) ?> segments</p>
      <div class="bar">
        <?php foreach (['sourced', 'generated', 'no_source_found'] as $kind): ?>
          <?php $pct = $cells ? ($totals[$kind] / $cells) * 100 : 0; ?>
          <span class="<?= $kind === 'no_source_found' ? 'empty' : $kind ?>" style="width: <?= $pct ?>%"></span>
        <?php endforeach; ?>
      </div>
      <div class="legend">
        <span><i class="dot" style="background: var(--green)"></i>Sourced <?= $totals['sourced'] ?></span>
        <span><i class="dot" style="background: var(--accent)"></i>Generated <?= $totals['generated'] ?></span>
        <span><i class="dot" style="background: #dfe7ec"></i>No source found <?= $totals['no_source_found'] ?></span>
      </div>
    </div>
  <?php endif; ?>

  <div class="toolbar">
    <strong style="color: var(--primary)">Courses</strong>
    <span style="color: var(--muted); font-size: .84rem">Reading from <code>data/generated/</code></span>
  </div>

  <div class="card-grid">
    <?php foreach ($courses as $course): ?>
      <?php
        $per = ['sourced' => 0, 'generated' => 0, 'no_source_found' => 0];
        foreach ($segments as $segment) {
            $per[segment_state($course, $segment)['provenance']]++;
        }
        $total = max(array_sum($per), 1);
      ?>
      <a class="course-card" href="course.php?course=<?= urlencode($course['course_key']) ?><?= $admin ? '&admin=1' : '' ?>">
        <h3><?= htmlspecialchars($course['name']) ?></h3>
        <p class="field"><?= htmlspecialchars($course['field']) ?></p>
        <div class="bar">
          <span class="sourced"   style="width: <?= $per['sourced'] / $total * 100 ?>%"></span>
          <span class="generated" style="width: <?= $per['generated'] / $total * 100 ?>%"></span>
          <span class="empty"     style="width: <?= $per['no_source_found'] / $total * 100 ?>%"></span>
        </div>
        <div class="legend">
          <?php if ($admin): ?>
            <span><?= $per['sourced'] ?> sourced</span>
            <span><?= $per['generated'] ?> generated</span>
            <?php if ($per['no_source_found']): ?><span><?= $per['no_source_found'] ?> empty</span><?php endif; ?>
          <?php else: ?>
            <span><?= $total - $per['no_source_found'] ?> of <?= $total ?> sections available</span>
          <?php endif; ?>
        </div>
      </a>
    <?php endforeach; ?>
  </div>
</div>

<footer>
  <strong>Career Portal Course Library</strong><br>
  Course information should guide exploration and should not replace official
  eligibility, admission or professional-regulation sources.
</footer>

</body>
</html>

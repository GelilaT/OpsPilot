# job-scheduling

## ADDED Requirements

### Requirement: Per-timezone dispatcher

A dispatcher endpoint called every 5 minutes SHALL compute due schedules per site timezone: nightly pipeline at 02:00 (for the previous business date), outcome evaluation at 06:00 and follow-ups at 16:00. It SHALL enqueue each once using a unique key per site, local date and job.

#### Scenario: Repeated ticks

- **WHEN** the dispatcher runs twice at 16:30 London time
- **THEN** the first tick enqueues the three jobs for each London site and the second enqueues nothing

#### Scenario: Simulated sites

- **WHEN** a site runs on the simulator clock
- **THEN** the dispatcher skips it, and `simulator.next_day` enqueues the same jobs for the simulated date in order on the site lock

# Proof Course

A short structural guide used to exercise the manifest loader and the course
validator. It is not meant to teach a subject; it only carries the required
sections in the required order.

## The short answer

The old model fails because it assumes every payload is a file on disk. The
course replaces that assumption with an execution model.

## How it works

A process is created, memory is allocated, and code is written into that memory
before execution. Each step leaves a distinct trace.

## Evidence and disagreements

Vendor documentation and independent measurement agree that process creation is
the common step. They disagree about which trace survives the longest.

## Procedure

Read the manifest, walk the ten modules, and review the glossary terms.

## Verify it worked

Run the manifest loader against this directory and confirm it returns ten
modules with unique numbers and slugs.

## Failure modes

A missing body file or a bad assignment type stops loading with a list of
errors.

## Limits and what this does not cover

This fixture does not cover live telemetry, response actions, or grading.

## Sources

- Vendor documentation, https://example.gov/doc
- Independent paper, https://example.org/paper

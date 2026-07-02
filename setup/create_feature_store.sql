-- Feature Store Schema Setup
-- Creates the dedicated schema for Snowflake Feature Store metadata.
-- The Feature Store Python API handles entity/feature view creation.

CREATE SCHEMA IF NOT EXISTS AUTO_FEATURE_ENG.FEATURE_STORE;

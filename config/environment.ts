/**
 * Environment Configuration
 * Configure different environments for your tests
 */

import { existsSync, readFileSync } from 'node:fs';

function loadLocalEnvFile(): void {
    const envPath = '.env';
    if (!existsSync(envPath)) {
        return;
    }

    const fileContent = readFileSync(envPath, 'utf-8');
    for (const rawLine of fileContent.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#')) {
            continue;
        }

        const equalsIndex = line.indexOf('=');
        if (equalsIndex <= 0) {
            continue;
        }

        const key = line.slice(0, equalsIndex).trim();
        if (!key || process.env[key] !== undefined) {
            continue;
        }

        let value = line.slice(equalsIndex + 1).trim();
        const isWrappedInMatchingQuotes =
            value.length >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'")));
        if (isWrappedInMatchingQuotes) {
            value = value.slice(1, -1);
        }

        process.env[key] = value;
    }
}

// Load local .env values for local runs before reading process.env defaults.
loadLocalEnvFile();

type Environment = 'staging' | 'uat' | 'production';

interface EnvironmentConfig {
    baseUrl: string;
    apiUrl: string;
    timeout: number;
}

const environments: Record<Environment, EnvironmentConfig> = {
    staging: {
        baseUrl: process.env.STAGING_BASE_URL || 'http://localhost:3000',
        apiUrl: process.env.STAGING_API_URL || 'http://localhost:8080',
        timeout: 30000,
    },
    uat: {
        baseUrl: process.env.UAT_BASE_URL || 'http://localhost:3000',
        apiUrl: process.env.UAT_API_URL || 'http://localhost:8080',
        timeout: 30000,
    },
    production: {
        baseUrl: process.env.PROD_BASE_URL || 'https://example.com',
        apiUrl: process.env.PROD_API_URL || 'https://api.example.com',
        timeout: 60000,
    },
};

// Get current environment from env variable or default to staging
const currentEnv = (process.env.TEST_ENV as Environment) || 'staging';

export const environment = {
    ...environments[currentEnv],
    env: currentEnv,

    // Test user credentials (use environment variables for sensitive data)
    testUser: {
        username: process.env.TEST_USERNAME || 'test@example.com',
        password: process.env.TEST_PASSWORD || '', // Never hardcode passwords
    },

    // API authentication
    apiKey: process.env.API_SECRET_KEY || '',

    // Feature flags
    features: {
        enableScreenshots: process.env.TAKE_SCREENSHOTS === 'true',
        enableVideoRecording: process.env.RECORD_VIDEOS === 'true',
        enableTracing: process.env.ENABLE_TRACING === 'true',
    },
};

export default environment;

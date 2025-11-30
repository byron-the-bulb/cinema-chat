import React, { useState, useEffect } from 'react';
import styles from '@/styles/AudioDeviceSelector.module.css';

interface PiAudioDevice {
  card: number;
  device: number;
  name: string;
  alsa_id: string;
}

const PiAudioDeviceSelector: React.FC = () => {
  const [devices, setDevices] = useState<PiAudioDevice[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configMessage, setConfigMessage] = useState<string>('');

  useEffect(() => {
    loadDevices();
  }, []);

  const loadDevices = async () => {
    try {
      setLoading(true);
      setError(null);

      // Call local Next.js API route (runs on the Pi)
      const response = await fetch('/api/pi/audio-devices');

      if (!response.ok) {
        throw new Error(`Failed to fetch devices: ${response.statusText}`);
      }

      const data = await response.json();
      setDevices(data.devices || []);

      // Select the first device by default for display only
      // (Actual configuration happens when Pi client starts)
      if (data.devices && data.devices.length > 0 && !selectedDevice) {
        const firstDevice = data.devices[0].alsa_id;
        setSelectedDevice(firstDevice);
        console.log(`Detected audio device: ${firstDevice} (will be auto-configured on session start)`);
      }
    } catch (err) {
      console.error('Error loading Pi audio devices:', err);
      setError(err instanceof Error ? err.message : 'Failed to load audio devices from Pi');
    } finally {
      setLoading(false);
    }
  };

  const handleDeviceChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const alsa_id = event.target.value;
    setSelectedDevice(alsa_id);
    setConfigMessage('');
    setError(null);

    try {
      // Call local Next.js API route (runs on the Pi)
      const response = await fetch('/api/pi/audio-device', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: alsa_id })
      });

      if (!response.ok) {
        throw new Error(`Failed to set device: ${response.statusText}`);
      }

      const result = await response.json();
      setConfigMessage(result.message || 'Audio device configured successfully');

      // Clear success message after 5 seconds
      setTimeout(() => setConfigMessage(''), 5000);
    } catch (err) {
      console.error('Error setting Pi audio device:', err);
      setError(err instanceof Error ? err.message : 'Failed to configure audio device');
    }
  };

  return (
    <div className={styles.audioDeviceSelector}>
      <label htmlFor="pi-mic-select">Pi Microphone Device: </label>
      {loading ? (
        <span className={styles.loading}>Loading Pi audio devices...</span>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : (
        <>
          <select
            id="pi-mic-select"
            value={selectedDevice}
            onChange={handleDeviceChange}
            className={styles.micSelect}
          >
            {devices.length === 0 ? (
              <option value="">No audio devices found on Pi</option>
            ) : (
              devices.map((dev) => (
                <option key={dev.alsa_id} value={dev.alsa_id}>
                  {dev.name} ({dev.alsa_id})
                </option>
              ))
            )}
          </select>
          {configMessage && (
            <div style={{
              marginTop: '8px',
              padding: '8px',
              backgroundColor: '#d4edda',
              color: '#155724',
              borderRadius: '4px',
              fontSize: '14px'
            }}>
              {configMessage}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default PiAudioDeviceSelector;

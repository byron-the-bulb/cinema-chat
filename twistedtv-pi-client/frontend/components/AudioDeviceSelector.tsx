import React, { useState, useEffect } from 'react';
import { useRTVIClientMediaDevices } from "@pipecat-ai/client-react";
import styles from '@/styles/AudioDeviceSelector.module.css';

interface AudioDevice {
  deviceId: string;
  label: string;
  kind: string;
}

interface AudioDeviceSelectorProps {
  insideProvider?: boolean;
  selectedDeviceId?: string;
  onDeviceSelect?: (deviceId: string) => void;
}

const AudioDeviceSelector: React.FC<AudioDeviceSelectorProps> = ({ 
  insideProvider = false,
  selectedDeviceId,
  onDeviceSelect
}) => {
  // State for devices when outside provider
  const [availableDevices, setAvailableDevices] = useState<AudioDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Use the hook if we're inside the provider
  const rtviDevices = insideProvider ? useRTVIClientMediaDevices() : null;

  // Function to get devices outside the provider
  useEffect(() => {
    if (insideProvider) return; // Skip if inside provider

    const getDevices = async () => {
      try {
        setLoading(true);
        setError(null);

        // Request permission to use media devices
        await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Get list of media devices
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputDevices = devices
          .filter(device => device.kind === 'audioinput')
          .map(device => ({
            deviceId: device.deviceId,
            label: device.label || `Microphone ${device.deviceId.slice(0, 5)}...`,
            kind: device.kind
          }));

        setAvailableDevices(audioInputDevices);
        
        // If no device is selected yet and we have devices, select the first one
        if (audioInputDevices.length > 0 && !selectedDeviceId && onDeviceSelect) {
          onDeviceSelect(audioInputDevices[0].deviceId);
        }
      } catch (err) {
        console.error('Error accessing media devices:', err);
        setError('Failed to access microphone. Please check your browser permissions.');
      } finally {
        setLoading(false);
      }
    };

    getDevices();

    // Set up device change listener (only if API is available)
    if (navigator.mediaDevices) {
      const handleDeviceChange = () => {
        getDevices();
      };

      navigator.mediaDevices.addEventListener('devicechange', handleDeviceChange);
      return () => {
        navigator.mediaDevices.removeEventListener('devicechange', handleDeviceChange);
      };
    }
  }, [insideProvider, onDeviceSelect, selectedDeviceId]);

  // Handle device selection outside provider
  const handleExternalMicChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const deviceId = event.target.value;
    if (onDeviceSelect) {
      onDeviceSelect(deviceId);
    }
  };

  // Handle device selection inside provider
  const handleInternalMicChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    if (rtviDevices) {
      rtviDevices.updateMic(event.target.value);
    }
  };

  // If inside provider, use the provider's state and methods
  if (insideProvider && rtviDevices) {
    // Set the initial microphone if we have a selectedDeviceId and it's in the available list
    useEffect(() => {
      if (selectedDeviceId && rtviDevices.availableMics.some(mic => mic.deviceId === selectedDeviceId)) {
        console.log('Setting initial microphone in provider to:', selectedDeviceId);
        rtviDevices.updateMic(selectedDeviceId);
      }
    }, [rtviDevices.availableMics, selectedDeviceId]);

    return (
      <div className={styles.audioDeviceSelector}>
        <label htmlFor="mic-select">Active Microphone: </label>
        {rtviDevices.availableMics.length === 0 ? (
          <span className={styles.loading}>Loading microphones...</span>
        ) : (
          <select
            id="mic-select"
            value={rtviDevices.selectedMic?.deviceId || ''}
            onChange={handleInternalMicChange}
            className={styles.micSelect}
          >
            {rtviDevices.availableMics.length === 0 ? (
              <option value="">No microphones available</option>
            ) : (
              rtviDevices.availableMics.map((mic) => (
                <option key={mic.deviceId} value={mic.deviceId}>
                  {mic.label || `Microphone ${mic.deviceId.slice(0, 5)}...`}
                </option>
              ))
            )}
          </select>
        )}
      </div>
    );
  }

  // Otherwise, use the browser's MediaDevices API
  return (
    <div className={styles.audioDeviceSelector}>
      <label htmlFor="mic-select">Select Microphone: </label>
      {loading ? (
        <span className={styles.loading}>Loading microphones...</span>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : (
        <select
          id="mic-select"
          value={selectedDeviceId || ''}
          onChange={handleExternalMicChange}
          className={styles.micSelect}
        >
          {availableDevices.length === 0 ? (
            <option value="">No microphones available</option>
          ) : (
            availableDevices.map((mic) => (
              <option key={mic.deviceId} value={mic.deviceId}>
                {mic.label}
              </option>
            ))
          )}
        </select>
      )}
    </div>
  );
};

export default AudioDeviceSelector;

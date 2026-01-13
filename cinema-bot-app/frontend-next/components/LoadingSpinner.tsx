import React from 'react';
import styles from '@/styles/LoadingSpinner.module.css';

interface LoadingSpinnerProps {
  message?: string;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ message = 'Loading...' }) => {
  return (
    <div className={styles.loadingSpinnerContainer}>
      <div className={styles.loadingSpinner}></div>
      <div className={styles.loadingMessage}>{message}</div>
    </div>
  );
};

export default LoadingSpinner;

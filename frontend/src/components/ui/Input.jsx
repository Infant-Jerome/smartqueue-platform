import { CONTROL_CLASS } from './controlClass';

/** Native input with SmartQueue styling. Keeps default form behavior. */
export default function Input({ className = '', ...rest }) {
  return <input className={`${CONTROL_CLASS} ${className}`} {...rest} />;
}

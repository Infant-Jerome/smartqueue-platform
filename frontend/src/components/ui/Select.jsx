import { CONTROL_CLASS } from './controlClass';

/** Native select with SmartQueue styling. Keeps default form behavior. */
export default function Select({ className = '', children, ...rest }) {
  return <select className={`${CONTROL_CLASS} ${className}`} {...rest}>{children}</select>;
}

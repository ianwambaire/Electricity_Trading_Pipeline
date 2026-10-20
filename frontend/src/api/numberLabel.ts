export const numberLabel = (value:number|null|undefined, digits=2) => value == null ? 'Unavailable' : value.toLocaleString(undefined,{maximumFractionDigits:digits})

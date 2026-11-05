import {createContext,useContext} from 'react'
import type {CurrentOperations} from '../api/currentOperations'
import type {ApiState} from '../hooks/useApi'
export const CurrentOperationsContext=createContext<(ApiState<CurrentOperations>&{retry:()=>void})|null>(null)
export function useCurrentOperations(){return useContext(CurrentOperationsContext)}

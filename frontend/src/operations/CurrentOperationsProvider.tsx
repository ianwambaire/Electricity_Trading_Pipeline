import type {ReactNode} from 'react'
import {api} from '../api/client'
import {useApi} from '../hooks/useApi'
import {CurrentOperationsContext} from './currentContext'
export function CurrentOperationsProvider({children}:{children:ReactNode}){
 const state=useApi(api.currentOperations)
 return <CurrentOperationsContext.Provider value={state}>{children}</CurrentOperationsContext.Provider>
}

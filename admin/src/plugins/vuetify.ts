import {aliases, mdi} from 'vuetify/iconsets/mdi-svg'
import {createVuetify} from 'vuetify'
import {VAlert} from 'vuetify/components/VAlert'
import {VApp} from 'vuetify/components/VApp'
import {VAppBar, VAppBarTitle} from 'vuetify/components/VAppBar'
import {VBtn} from 'vuetify/components/VBtn'
import {VCard, VCardActions, VCardText, VCardTitle} from 'vuetify/components/VCard'
import {VChip} from 'vuetify/components/VChip'
import {VDialog} from 'vuetify/components/VDialog'
import {VForm} from 'vuetify/components/VForm'
import {VContainer, VSpacer} from 'vuetify/components/VGrid'
import {VList, VListItem, VListItemTitle} from 'vuetify/components/VList'
import {VMain} from 'vuetify/components/VMain'
import {VMenu} from 'vuetify/components/VMenu'
import {VNavigationDrawer} from 'vuetify/components/VNavigationDrawer'
import {VSelect} from 'vuetify/components/VSelect'
import {VTable} from 'vuetify/components/VTable'
import {VTextField} from 'vuetify/components/VTextField'

/**
 * Vuetify as BOA, Damien, Diablo and the BMU set it up: components registered by hand (add each one here when a
 * screen first uses it, so the bundle holds only what the app uses) and icons from @mdi/js.
 */
export default createVuetify({
  components: {
    VAlert, VApp, VAppBar, VAppBarTitle, VBtn, VCard, VCardActions, VCardText, VCardTitle, VChip, VContainer,
    VDialog, VForm, VList, VListItem, VListItemTitle, VMain, VMenu, VNavigationDrawer, VSelect, VSpacer, VTable,
    VTextField
  },
  icons: {defaultSet: 'mdi', aliases, sets: {mdi}},
  defaults: {
    VTextField: {variant: 'outlined', density: 'comfortable'},
    VSelect: {variant: 'outlined', density: 'comfortable'}
  }
})

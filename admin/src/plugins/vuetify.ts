import './main.scss'
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
 * Vuetify as BOA, Damien, Diablo and the BMU set it up: its styles (main.scss: without them the components render
 * unstyled), components registered by hand (add each one here when a screen first uses it, so the bundle holds only
 * what the app uses), icons from @mdi/js, the BMU's control defaults, and BOA's light-theme colours.
 */
export default createVuetify({
  components: {
    VAlert, VApp, VAppBar, VAppBarTitle, VBtn, VCard, VCardActions, VCardText, VCardTitle, VChip, VContainer,
    VDialog, VForm, VList, VListItem, VListItemTitle, VMain, VMenu, VNavigationDrawer, VSelect, VSpacer, VTable,
    VTextField
  },
  icons: {defaultSet: 'mdi', aliases, sets: {mdi}},
  defaults: {
    VBtn: {style: 'text-transform: none;'},
    VTextField: {variant: 'outlined', density: 'compact'},
    VSelect: {variant: 'outlined', density: 'compact'}
  },
  theme: {
    themes: {
      light: {
        colors: {
          anchor: '#37769a',
          body: '#212529',
          error: '#cf1715',
          info: '#367da1',
          primary: '#37769a',
          secondary: '#96C3de',
          success: '#437f4b',
          tertiary: '#125074',
          topbar: '#125074',
          warning: '#C74600'
        }
      }
    }
  }
})

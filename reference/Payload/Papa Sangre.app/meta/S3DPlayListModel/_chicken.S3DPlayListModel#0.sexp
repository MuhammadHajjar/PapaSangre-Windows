(playlist
  (name "_chicken")                     ;;; name used as the playlist key
  (repeat none)							;;; pick either of: none, start(first), last

  (sound
    (spatialized true)
    (bundle
      (path "ps1/spatialized")
      (name "chicken_alarm_trigger_ver_A")
      (extension "m4a")))
  (sound
    (spatialized true)
    (bundle
      (path "ps1/spatialized")
      (name "chicken_alarm_trigger_ver_B")
      (extension "m4a")))
  (sound
    (spatialized true)
    (bundle
      (path "ps1/spatialized")
      (name "chicken_alarm_living")
      (extension "m4a")))
  (sound
    (spatialized false)
    (unloadonstop true)
    (bundle
      (path "ps1/reactions")
      (name "chicken_alarm_Collect")
      (extension "m4a"))
))